import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "bot.db"

logger = logging.getLogger(__name__)


# =========================
# CONEXÃO
# =========================

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


# =========================
# USERS
# =========================

def get_or_create_user(telegram_id: int, nome: str | None = None):
    with get_db() as db:
        cur = db.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cur.fetchone()

        if row:
            return row["id"]

        db.execute(
            """
            INSERT INTO users (telegram_id, nome, criado_em)
            VALUES (?, ?, ?)
            """,
            (telegram_id, nome, now_iso())
        )

        return db.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]


# =========================
# PAYMENTS (payments_v2)
# =========================

def create_payment(
    user_id: int,
    gateway: str,
    plan: str,
    amount: float,
    expires_in_minutes: int,
    gateway_payment_id: str | None = None,
    idempotency_key: str | None = None,
):
    expires_at = (
        datetime.utcnow() + timedelta(minutes=expires_in_minutes)
    ).isoformat()

    with get_db() as db:
        db.execute(
            """
            INSERT INTO payments_v2 (
                user_id,
                gateway,
                gateway_payment_id,
                idempotency_key,
                plan,
                amount,
                status,
                expires_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                user_id,
                gateway,
                gateway_payment_id,
                idempotency_key,
                plan,
                amount,
                expires_at,
                now_iso()
            )
        )


def get_pending_payment(user_id: int):
    with get_db() as db:
        cur = db.execute(
            """
            SELECT *
            FROM payments_v2
            WHERE user_id = ?
              AND status = 'pending'
              AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id, now_iso())
        )
        return cur.fetchone()


def confirm_payment(gateway_payment_id: str):
    """
    Idempotente:
    - Se já confirmado, retorna o pagamento
    - Se pending, confirma e retorna
    """
    with get_db() as db:
        cur = db.execute(
            """
            SELECT *
            FROM payments_v2
            WHERE gateway_payment_id = ?
            """,
            (gateway_payment_id,)
        )
        payment = cur.fetchone()

        if not payment:
            raise ValueError("Pagamento não encontrado")

        if payment["status"] == "confirmed":
            return payment

        db.execute(
            """
            UPDATE payments_v2
            SET status = 'confirmed',
                confirmed_at = ?
            WHERE id = ?
            """,
            (now_iso(), payment["id"])
        )

        # Recarrega registro atualizado
        cur = db.execute(
            "SELECT * FROM payments_v2 WHERE id = ?",
            (payment["id"],)
        )
        return cur.fetchone()


# =========================
# SUBSCRIPTIONS
# =========================

def get_active_subscription(user_id: int):
    with get_db() as db:
        cur = db.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE user_id = ?
              AND status = 'active'
              AND ends_at > ?
            LIMIT 1
            """,
            (user_id, now_iso())
        )
        return cur.fetchone()

# =========================
# FOLLOW-UPS / REMINDERS
# =========================

def get_expired_pending_payments():
    """
    Pagamentos pendentes cujo prazo expirou
    """
    with get_db() as db:
        cur = db.execute(
            """
            SELECT *
            FROM payments_v2
            WHERE status = 'pending'
              AND expires_at <= ?
            """,
            (now_iso(),)
        )
        return cur.fetchall()


def get_pending_payments_for_reminder(max_reminders: int = 3):
    """
    Pagamentos pendentes ainda válidos
    e que podem receber lembrete
    """
    with get_db() as db:
        cur = db.execute(
            """
            SELECT *
            FROM payments_v2
            WHERE status = 'pending'
              AND expires_at > ?
              AND reminders_sent < ?
            """,
            (now_iso(), max_reminders)
        )
        return cur.fetchall()


def increment_payment_reminder(payment_id: int):
    """
    Marca envio de lembrete
    """
    with get_db() as db:
        db.execute(
            """
            UPDATE payments_v2
            SET reminders_sent = reminders_sent + 1
            WHERE id = ?
            """,
            (payment_id,)
        )


def get_confirmed_unprocessed_payments():
    """
    Pagamentos confirmados que ainda não geraram assinatura
    """
    with get_db() as db:
        cur = db.execute(
            """
            SELECT p.*
            FROM payments_v2 p
            LEFT JOIN subscriptions s
              ON s.payment_id = p.id
            WHERE p.status = 'confirmed'
              AND s.id IS NULL
            """
        )
        return cur.fetchall()

def get_last_payment_by_user(user_id: int):
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                gateway_payment_id,
                status,
                expires_at
            FROM payments_v2
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "gateway_payment_id": row[1],
        "status": row[2],
        "expires_at": row[3],
    }


# =========================
# INIT / MIGRATIONS
# =========================

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                nome        TEXT,
                criado_em   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments_v2 (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL,
                gateway             TEXT NOT NULL,
                gateway_payment_id  TEXT,
                idempotency_key     TEXT,
                plan                TEXT NOT NULL,
                amount              REAL NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending',
                expires_at          TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                confirmed_at        TEXT,
                reminders_sent      INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
