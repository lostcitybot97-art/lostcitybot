import logging
from datetime import datetime, timedelta

import psycopg2.extras

from app.infra import db
from app.domain.plans import PLANS

logger = logging.getLogger(__name__)


def activate_subscription_from_payment(payment_id: int):
    """
    Dado um payments_v2.id confirmado,
    cria ou estende assinatura.
    Idempotente por definição.
    """

    with db.get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1️⃣ Buscar pagamento
        cur.execute(
            "SELECT * FROM payments_v2 WHERE id = %s",
            (payment_id,)
        )
        payment = cur.fetchone()

        if not payment:
            raise ValueError("Pagamento não encontrado")

        if payment["status"] != "confirmed":
            raise ValueError("Pagamento ainda não confirmado")

        # 2️⃣ Idempotência
        cur.execute(
            "SELECT * FROM subscriptions WHERE payment_id = %s",
            (payment_id,)
        )
        existing_sub = cur.fetchone()

        if existing_sub:
            logger.info("Pagamento já processado", extra={"payment_id": payment_id})
            return existing_sub

        user_id = payment["user_id"]
        plan = payment["plan"]

        if plan not in PLANS:
            raise ValueError(f"Plano desconhecido: {plan}")

        days = PLANS[plan]["days"]
        now = datetime.utcnow()

        # 3️⃣ Buscar assinatura ativa
        cur.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id = %s AND status = 'active' AND ends_at > %s
            LIMIT 1
            """,
            (user_id, now.isoformat())
        )
        current_sub = cur.fetchone()

        if current_sub:
            base_end = datetime.fromisoformat(current_sub["ends_at"])
            starts_at = datetime.fromisoformat(current_sub["starts_at"])

            # Expira anterior
            cur.execute(
                "UPDATE subscriptions SET status = 'expired' WHERE id = %s",
                (current_sub["id"],)
            )
        else:
            base_end = now
            starts_at = now

        new_ends_at = base_end + timedelta(days=days)

        # 4️⃣ Criar nova assinatura
        cur.execute(
            """
            INSERT INTO subscriptions (
                user_id,
                payment_id,
                plan,
                status,
                starts_at,
                ends_at
            )
            VALUES (%s, %s, %s, 'active', %s, %s)
            RETURNING *
            """,
            (
                user_id,
                payment_id,
                plan,
                starts_at.isoformat(),
                new_ends_at.isoformat(),
            )
        )

        sub = cur.fetchone()

        logger.info(
            "Assinatura ativada",
            extra={
                "user_id": user_id,
                "plan": plan,
                "ends_at": new_ends_at.isoformat(),
            }
        )

        return sub
