import logging
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

from app.infra import db
from app.domain.plans import PLANS

logger = logging.getLogger(__name__)


def activate_subscription_from_payment(payment_id: int):
    """
    Processa pagamento confirmado e cria/estende assinatura.
    Idempotente, seguro contra concorrência e falhas.
    """

    with db.get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 🔒 1. Lock no pagamento (evita concorrência entre jobs)
        cur.execute(
            "SELECT * FROM payments_v2 WHERE id = %s FOR UPDATE",
            (payment_id,)
        )
        payment = cur.fetchone()

        if not payment:
            logger.warning(f"[ERRO] Pagamento não encontrado: {payment_id}")
            return

        if payment["status"] != "confirmed":
            logger.info(f"[SKIP] Pagamento não confirmado: {payment_id}")
            return

        # 🔁 2. Idempotência (já existe subscription)
        cur.execute(
            "SELECT * FROM subscriptions WHERE payment_id = %s",
            (payment_id,)
        )
        existing_sub = cur.fetchone()

        if existing_sub:
            logger.info(f"[IDEMPOTENTE] Já processado: payment_id={payment_id}")
            return existing_sub

        user_id = payment["user_id"]
        plan = payment["plan"]

        if plan not in PLANS:
            logger.error(f"[ERRO] Plano desconhecido: {plan}")
            return

        days = PLANS[plan]["days"]
        now = datetime.utcnow()

        # 🔎 3. Busca assinatura ativa
        cur.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id = %s
              AND status = 'active'
              AND ends_at > %s
            LIMIT 1
            """,
            (user_id, now.isoformat())
        )
        current_sub = cur.fetchone()

        if current_sub:
base_end = current_sub["ends_at"]
starts_at = current_sub["starts_at"]
            # Expira antiga
            cur.execute(
                "UPDATE subscriptions SET status = 'expired' WHERE id = %s",
                (current_sub["id"],)
            )
        else:
            base_end = now
            starts_at = now

        new_ends_at = base_end + timedelta(days=days)

        # 🛡️ 4. Insert protegido contra duplicidade
        try:
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
                ON CONFLICT (payment_id) DO NOTHING
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

            if not sub:
                logger.info(f"[IDEMPOTENTE] Insert ignorado: payment_id={payment_id}")
                return

            logger.info(
                "[OK] Assinatura ativada",
                extra={
                    "user_id": user_id,
                    "payment_id": payment_id,
                    "plan": plan,
                    "ends_at": new_ends_at.isoformat(),
                }
            )

            return sub

        except psycopg2.errors.UniqueViolation:
            # fallback absoluto (caso constraint ainda não esteja criada)
            logger.warning(f"[RACE] UniqueViolation capturada: payment_id={payment_id}")
            return
