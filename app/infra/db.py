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


def get_last_payment_by_user(user_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, gateway_payment_id, status, expires_at
            FROM payments_v2 WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        return cur.fetchone()


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
            SELECT p.* FROM payments_v2 p
            LEFT JOIN subscriptions s ON s.payment_id = p.id
            WHERE p.status = 'confirmed' AND s.id IS NULL
        """)
        return cur.fetchall()


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
