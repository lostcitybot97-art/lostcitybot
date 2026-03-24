import os
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso():
    return datetime.utcnow().isoformat()


def get_or_create_user(telegram_id: int, nome: str = None):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO users (telegram_id, nome, criado_em) VALUES (%s, %s, %s) RETURNING id",
            (telegram_id, nome, now_iso())
        )
        return cur.fetchone()["id"]


def create_payment(user_id, gateway, plan, amount, expires_in_minutes,
                   gateway_payment_id=None, idempotency_key=None):
    expires_at = (datetime.utcnow() + timedelta(minutes=expires_in_minutes)).isoformat()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO payments_v2
                (user_id, gateway, gateway_payment_id, idempotency_key,
                 plan, amount, status, expires_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
        """, (user_id, gateway, gateway_payment_id, idempotency_key,
              plan, amount, expires_at, now_iso()))


def get_pending_payment(user_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM payments_v2
            WHERE user_id = %s AND status = 'pending' AND expires_at > %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, now_iso()))
        return cur.fetchone()


def confirm_payment(gateway_payment_id: str):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM payments_v2 WHERE gateway_payment_id = %s", (gateway_payment_id,))
        payment = cur.fetchone()
        if not payment:
            raise ValueError("Pagamento não encontrado")
        if payment["status"] == "confirmed":
            return payment
        cur.execute("""
            UPDATE payments_v2 SET status = 'confirmed', confirmed_at = %s WHERE id = %s
        """, (now_iso(), payment["id"]))
        cur.execute("SELECT * FROM payments_v2 WHERE id = %s", (payment["id"],))
        return cur.fetchone()


def get_active_subscription(user_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM subscriptions
            WHERE user_id = %s AND status = 'active' AND ends_at > %s LIMIT 1
        """, (user_id, now_iso()))
        return cur.fetchone()


def schedule_expiration_reminders():
    """
    Cria tasks de aviso de expiração (D-3, D-2, D-1) para assinaturas
    ativas com pagamento confirmado.

    Garante 1 task por (subscription_id, days_left).
    """
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1) Buscar assinaturas elegíveis (3, 2 ou 1 dia para acabar)
        cur.execute(
            """
            SELECT
              s.id               AS subscription_id,
              s.user_id,
              s.plan,
              s.ends_at,
              p.id               AS payment_id,
              FLOOR(EXTRACT(EPOCH FROM (s.ends_at - NOW())) / 86400)::int AS days_left
            FROM subscriptions s
            JOIN payments_v2 p
              ON p.id = s.payment_id
            WHERE
              s.status = 'active'
              AND p.status = 'confirmed'
              AND FLOOR(EXTRACT(EPOCH FROM (s.ends_at - NOW())) / 86400)::int IN (1, 2, 3)
            """,
        )
        rows = cur.fetchall()

        logger.info("[REMINDERS] assinaturas elegíveis: %d", len(rows))

        if not rows:
            return

        insert_cur = conn.cursor()

        # 2) Para cada assinatura, criar task se ainda não existir
        for row in rows:
            subscription_id = row["subscription_id"]
            user_id = row["user_id"]
            days_left = row["days_left"]

            # Evitar duplicatas: já existe task para esse sub + days_left?
            insert_cur.execute(
                """
                SELECT 1
                FROM outbox_tasks
                WHERE
                    user_id = %s
                    AND task_type = 'SUBSCRIPTION_EXPIRY_WARNING'
                    AND metadata->>'subscription_id' = %s
                    AND (metadata->>'days_left')::int = %s
                LIMIT 1
                """,
                (user_id, str(subscription_id), days_left),
            )
            already_exists = insert_cur.fetchone()
            if already_exists:
                continue

            # Cria task na outbox, metadata básica
            insert_cur.execute(
                """
                INSERT INTO outbox_tasks (user_id, task_type, status, scheduled_for, metadata)
                VALUES (
                    %s,
                    'SUBSCRIPTION_EXPIRY_WARNING',
                    'pending',
                    NOW(),
                    jsonb_build_object(
                        'subscription_id', %s,
                        'plan', %s,
                        'days_left', %s
                    )
                )
                """,
                (user_id, subscription_id, row["plan"], days_left),
            )


def get_last_payment_by_user(user_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, gateway_payment_id, status, expires_at
            FROM payments_v2 WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        return cur.fetchone()


def get_payments_history_by_user(user_id: int, limit: int = 10):
    """
    Retorna os últimos pagamentos de um usuário (mais recentes primeiro).
    """
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                id,
                plan,
                amount,
                status,
                created_at,
                expires_at,
                confirmed_at,
                gateway,
                gateway_payment_id
            FROM payments_v2
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def get_payment_by_gateway_id(gateway_payment_id: str):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM payments_v2 WHERE gateway_payment_id = %s LIMIT 1",
            (str(gateway_payment_id),)
        )
        return cur.fetchone()


def update_payment_status(payment_id: int, status: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE payments_v2
            SET status = %s,
                confirmed_at = CASE WHEN %s = 'confirmed' THEN %s ELSE confirmed_at END
            WHERE id = %s
        """, (status, status, now_iso(), payment_id))


def get_expired_pending_payments():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM payments_v2 WHERE status = 'pending' AND expires_at <= %s
        """, (now_iso(),))
        return cur.fetchall()


def get_pending_payments_for_reminder(max_reminders: int = 3):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM payments_v2
            WHERE status = 'pending' AND expires_at > %s AND reminders_sent < %s
        """, (now_iso(), max_reminders))
        return cur.fetchall()


def increment_payment_reminder(payment_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE payments_v2 SET reminders_sent = reminders_sent + 1 WHERE id = %s",
            (payment_id,)
        )


def get_confirmed_unprocessed_payments():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT p.*
            FROM payments_v2 p
            LEFT JOIN subscriptions s ON s.payment_id = p.id
            WHERE p.status = 'confirmed' AND s.id IS NULL
            ORDER BY p.created_at DESC
            LIMIT 10
        """)
        return cur.fetchall()


def get_user_by_id(user_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                nome        TEXT,
                criado_em   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments_v2 (
                id                  SERIAL PRIMARY KEY,
                user_id             INTEGER NOT NULL,
                gateway             TEXT NOT NULL,
                gateway_payment_id  TEXT,
                external_reference  TEXT,
                idempotency_key     TEXT,
                plan                TEXT NOT NULL,
                amount              REAL NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending',
                expires_at          TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                confirmed_at        TEXT,
                reminders_sent      INTEGER NOT NULL DEFAULT 0,
                pix_qr_code         TEXT,
                pix_qr_code_base64  TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                payment_id  INTEGER,
                plan        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                starts_at   TEXT NOT NULL,
                ends_at     TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (payment_id) REFERENCES payments_v2(id)
            );
        """)


def get_active_subscription_with_days(user_id: int):
    """
    Retorna assinatura ativa + dias restantes para um user_id.
    """
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                s.*,
                GREATEST(
                    0,
                    FLOOR(EXTRACT(EPOCH FROM (s.ends_at::timestamp - NOW())) / 86400)
                ) AS dias_restantes
            FROM subscriptions s
            WHERE
                s.user_id = %s
                AND s.status = 'active'
                AND s.ends_at > %s
            ORDER BY s.ends_at DESC
            LIMIT 1
            """,
            (user_id, now_iso()),
        )
        return cur.fetchone()


def get_recently_expired_subscriptions(window_minutes: int = 10):
    now = datetime.utcnow()
    now_str = now.isoformat()
    window_str = f"{window_minutes} minutes"

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT s.*, u.telegram_id
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE
                s.status = 'active'
                AND s.ends_at <= %s::timestamptz
                AND s.ends_at > (%s::timestamptz - INTERVAL %s)
            """,
            (now_str, now_str, window_str),
        )
        rows = cur.fetchall()

        if rows:
            ids = [r["id"] for r in rows]
            cur.execute(
                "UPDATE subscriptions SET status = 'expired' WHERE id = ANY(%s)",
                (ids,),
            )

        return rows

