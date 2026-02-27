import sqlite3
import logging
import uuid
from datetime import datetime, timedelta, timezone

import mercadopago

from app import config
from app.infra.db import get_db, get_pending_payment
from app.domain.plans import get_plan

logger = logging.getLogger(__name__)

# =========================
# MERCADO PAGO SDK
# =========================

sdk = mercadopago.SDK(config.MP_ACCESS_TOKEN)

# =========================
# CRIAR PIX
# =========================

def create_pix_payment(user_id: int, plan: str):
    """
    Cria um pagamento Pix no Mercado Pago.

    REGRAS:
    - Se existe PIX pendente do MESMO PLANO → reutiliza
    - Se existe PIX pendente de PLANO DIFERENTE → expira antigo e gera novo
    - Se não existe PIX pendente → gera novo

    Idempotência garantida por:
    - Regra de código
    - Índice único parcial no banco (status = 'pending')
    """

    # 1️⃣ Validar plano no domínio
    plan_data = get_plan(plan)
    if not plan_data:
        raise ValueError(f"Plano inválido: {plan}")

    amount = plan_data["price"]

    # 2️⃣ Verificar se já existe PIX pendente
    pending = get_pending_payment(user_id)
    if pending:
        pending = dict(pending)

    if pending:
        # Mesmo plano → reutiliza
        if pending["plan"] == plan:
            logger.info(
                "PIX pendente existente (mesmo plano) — reutilizando",
                extra={
                    "user_id": user_id,
                    "plan": plan,
                    "gateway_payment_id": pending["gateway_payment_id"],
                },
            )

            return {
                "id": pending["gateway_payment_id"],
                "external_reference": pending["external_reference"],
                "point_of_interaction": {
                    "transaction_data": {
                        "qr_code": pending["pix_qr_code"],
                        "qr_code_base64": pending.get("pix_qr_code_base64"),
                    }
                },
            }

        # Plano diferente → expira antigo
        logger.info(
            "Plano diferente detectado — expirando PIX antigo",
            extra={
                "user_id": user_id,
                "old_plan": pending["plan"],
                "new_plan": plan,
            },
        )

        with get_db() as conn:
            conn.execute(
                """
                UPDATE payments_v2
                SET status = 'expired'
                WHERE user_id = ? AND status = 'pending'
                """,
                (user_id,),
            )

    # 3️⃣ Gerar novo PIX no Mercado Pago
    external_reference = str(uuid.uuid4())

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    date_of_expiration = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payment_data = {
        "transaction_amount": amount,
        "description": plan_data["title"],
        "payment_method_id": "pix",
        "payer": {
            "email": f"user{user_id}@telegram.bot"
        },
        "external_reference": external_reference,
        "date_of_expiration": date_of_expiration,
    }

    logger.info(
        "Gerando novo PIX",
        extra={
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "external_reference": external_reference,
        },
    )

    result = sdk.payment().create(payment_data)

    if result["status"] not in (200, 201):
        logger.error(
            "Erro ao criar pagamento no Mercado Pago",
            extra={"response": result},
        )
        raise RuntimeError("Erro ao gerar Pix no Mercado Pago")

    payment = result["response"]

    tx = payment["point_of_interaction"]["transaction_data"]
    qr_code = tx["qr_code"]
    qr_code_base64 = tx.get("qr_code_base64")

    # 4️⃣ Persistir no banco com blindagem de idempotência
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO payments_v2 (
                    user_id,
                    gateway,
                    gateway_payment_id,
                    external_reference,
                    plan,
                    amount,
                    status,
                    expires_at,
                    created_at,
                    pix_qr_code,
                    pix_qr_code_base64
                ) VALUES (
                    ?, 'mercadopago', ?, ?, ?, ?, 'pending', ?, ?, ?, ?
                )
                """,
                (
                    user_id,
                    payment["id"],
                    external_reference,
                    plan,
                    amount,
                    date_of_expiration,
                    datetime.utcnow().isoformat(),
                    qr_code,
                    qr_code_base64,
                ),
            )

    except sqlite3.IntegrityError:
        logger.warning(
            "Idempotência acionada — PIX pendente já existe",
            extra={
                "user_id": user_id,
                "plan": plan,
            },
        )

        pending = get_pending_payment(user_id)

        if not pending:
            raise RuntimeError(
                "Violação de idempotência sem pagamento pendente encontrado"
            )

        return {
            "id": pending["gateway_payment_id"],
            "external_reference": pending["external_reference"],
            "point_of_interaction": {
                "transaction_data": {
                    "qr_code": pending["pix_qr_code"],
                    "qr_code_base64": pending.get("pix_qr_code_base64"),
                }
            },
        }

    logger.info(
        "PIX criado com sucesso",
        extra={
            "user_id": user_id,
            "plan": plan,
            "payment_id": payment["id"],
        },
    )

    return {
        "id": payment["id"],
        "external_reference": external_reference,
        "point_of_interaction": {
            "transaction_data": {
                "qr_code": qr_code,
                "qr_code_base64": qr_code_base64,
            }
        },
    }

# =========================
# CONSULTAR STATUS
# =========================

def check_payment_status(external_reference: str) -> str | None:
    """
    Consulta o status de um pagamento usando external_reference.
    Retorna o status do Mercado Pago ou None.
    """

    result = sdk.payment().search(
        {"external_reference": external_reference}
    )

    if result["status"] != 200:
        logger.warning(
            "Falha ao consultar status do pagamento",
            extra={"external_reference": external_reference},
        )
        return None

    results = result["response"].get("results", [])
    if not results:
        return None

    return results[0].get("status")
