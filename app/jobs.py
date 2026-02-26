import logging
from app.infra import db
from app.domain.subscriptions import activate_subscription_from_payment


logger = logging.getLogger(__name__)


def process_expired_payments():
    """
    Marca pagamentos expirados (lógica futura).
    Por enquanto, apenas loga.
    """
    expired = db.get_expired_pending_payments()

    for payment in expired:
        logger.info(
            "[FOLLOW-UP] Pagamento expirado detectado",
            extra={
                "payment_id": payment["id"],
                "user_id": payment["user_id"],
                "plan": payment["plan"],
            }
        )


def process_pending_payment_reminders():
    """
    Processa lembretes de pagamentos pendentes.
    Ainda NÃO envia mensagem.
    """
    pendings = db.get_pending_payments_for_reminder()

    for payment in pendings:
        logger.info(
            "[FOLLOW-UP] Pagamento pendente elegível para lembrete",
            extra={
                "payment_id": payment["id"],
                "user_id": payment["user_id"],
                "plan": payment["plan"],
                "reminders_sent": payment["reminders_sent"],
            }
        )

        # Marca que "enviaria" lembrete
        db.increment_payment_reminder(payment["id"])


def process_confirmed_payments():
    """
    Job canônico:
    Pagamento confirmado -> assinatura ativa.
    Seguro para rodar N vezes (idempotente).
    """
    payments = db.get_confirmed_unprocessed_payments()

    for payment in payments:
        try:
            logger.info(
                "[JOB] Processando pagamento confirmado",
                extra={
                    "payment_id": payment["id"],
                    "user_id": payment["user_id"],
                    "plan": payment["plan"],
                }
            )

            activate_subscription_from_payment(payment["id"])

        except Exception:
            logger.exception(
                "[JOB] Falha ao processar pagamento confirmado",
                extra={"payment_id": payment["id"]},
            )

