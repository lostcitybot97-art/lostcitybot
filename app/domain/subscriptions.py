import logging
from datetime import datetime, timedelta

from app.infra import db
from app.domain.plans import PLANS

logger = logging.getLogger(__name__)


def activate_subscription_from_payment(payment_id: int):
    """
    Regra canônica de domínio.
    Dado um payments_v2.id confirmado, cria ou estende assinatura.
    Idempotente por definição.
    """

    # 1. Buscar pagamento
    with db.get_db() as conn:
        payment = conn.execute(
            """
            SELECT *
            FROM payments_v2
            WHERE id = ?
            """,
            (payment_id,)
        ).fetchone()

    if not payment:
        raise ValueError("Pagamento não encontrado")

    # 2. Garantir pagamento confirmado
    if payment["status"] != "confirmed":
        raise ValueError("Pagamento ainda não confirmado")

    # 2b. Idempotência: pagamento já usado?
    with db.get_db() as conn:
        existing_sub = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE payment_id = ?
            """,
            (payment["id"],)
        ).fetchone()

    if existing_sub:
        logger.info(
            "Pagamento já processado para assinatura",
            extra={"payment_id": payment["id"]}
        )
        return existing_sub

    user_id = payment["user_id"]
    plan = payment["plan"]

    if plan not in PLANS:
        raise ValueError(f"Plano desconhecido: {plan}")

    days = PLANS[plan]["days"]
    now = datetime.utcnow()

    # 3. Buscar assinatura ativa atual
    current_sub = db.get_active_subscription(user_id)

    if current_sub:
        # Empilhamento: começa do fim atual
        base_end = datetime.fromisoformat(current_sub["ends_at"])
        starts_at = datetime.fromisoformat(current_sub["starts_at"])
    else:
        # Nova assinatura
        base_end = now
        starts_at = now

    new_ends_at = base_end + timedelta(days=days)

    # 4. Expirar assinatura anterior (se existir)
    if current_sub:
        with db.get_db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET status = 'expired'
                WHERE id = ?
                """,
                (current_sub["id"],)
            )

    # 5. Criar nova assinatura ligada ao payments_v2.id
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (
                user_id,
                plan,
                starts_at,
                ends_at,
                payment_id,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                user_id,
                plan,
                starts_at.isoformat(),
                new_ends_at.isoformat(),
                payment["id"],
                now.isoformat(),
            )
        )

        sub = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE payment_id = ?
            """,
            (payment["id"],)
        ).fetchone()

    logger.info(
        "Assinatura ativada",
        extra={
            "user_id": user_id,
            "plan": plan,
            "starts_at": starts_at.isoformat(),
            "ends_at": new_ends_at.isoformat(),
            "payment_id": payment["id"],
        }
    )

    return sub

