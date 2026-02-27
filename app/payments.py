import logging
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import mercadopago

from app import config
from app.infra.db import get_db, get_pending_payment
from app.domain.plans import get_plan

logger = logging.getLogger(__name__)

sdk = mercadopago.SDK(config.MP_ACCESS_TOKEN)


def create_pix_payment(user_id: int, plan: str):
    plan_data = get_plan(plan)
    if not plan_data:
        raise ValueError(f"Plano inválido: {plan}")

    amount = plan_data["price"]

    pending = get_pending_payment(user_id)
    if pending:
        pending = dict(pending)

    if pending:
        if pending["plan"] == plan:
            logger.info("PIX pendente existente (mesmo plano) — reutilizando")
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

        logger.info("Plano diferente — expirando PIX antigo")
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE payments_v2 SET status = 'expired' WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )

    external_reference = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    date_of_expiration = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payment_data = {
        "transaction_amount": amount,
        "description": plan_data["title"],
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@telegram.bot"},
        "external_reference": external_reference,
        "date_of_expiration": date_of_expiration,
    }

    logger.info("Gerando novo PIX")
    result = sdk.payment().create(payment_data)

    if result["status"] not in (200, 201):
        logger.error(
            "Erro ao criar pagamento no Mercado Pago: status=%s body=%s",
            result["status"],
            result.get("response", result),
        )
        raise RuntimeError("Erro ao gerar Pix no Mercado Pago")

    payment = result["response"]
    tx = payment["point_of_interaction"]["transaction_data"]
    qr_code = tx["qr_code"]
    qr_code_base64 = tx.get("qr_code_base64")

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO payments_v2 (
                    user_id, gateway, gateway_payment_id, external_reference,
                    plan, amount, status, expires_at, created_at,
                    pix_qr_code, pix_qr_code_base64
                ) VALUES (%s, 'mercadopago', %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                """,
                (
                    user_id, payment["id"], external_reference, plan, amount,
                    date_of_expiration, datetime.utcnow().isoformat(),
                    qr_code, qr_code_base64,
                ),
            )
    except psycopg2.IntegrityError:
        logger.warning("Idempotência acionada — PIX pendente já existe")
        pending = get_pending_payment(user_id)
        if not pending:
            raise RuntimeError("Violação de idempotência sem pagamento pendente encontrado")
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

    logger.info("PIX criado com sucesso — payment_id=%s", payment["id"])
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


def check_payment_status(gateway_payment_id: str) -> str | None:
    result = sdk.payment().get(gateway_payment_id)

    if result["status"] != 200:
        logger.warning("Falha ao consultar status do pagamento: %s", gateway_payment_id)
        return None

    return result["response"].get("status")
