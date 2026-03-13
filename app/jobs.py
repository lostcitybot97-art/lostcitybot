import logging
from app.infra import db
from app.domain.subscriptions import activate_subscription_from_payment
from app import config

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

async def revoke_expired_group_access(application):
    """
    Remove do grupo quem acabou de expirar a assinatura.
    """
    expired = db.get_recently_expired_subscriptions(window_minutes=10)

    for sub in expired:
        telegram_id = sub["telegram_id"]
        try:
            # remove o usuário do grupo
            await application.bot.ban_chat_member(
                chat_id=config.GRUPO_ID,
                user_id=telegram_id,
            )
            # unban para permitir voltar no futuro via novo invite
            await application.bot.unban_chat_member(
                chat_id=config.GRUPO_ID,
                user_id=telegram_id,
                only_if_banned=True,
            )
            logger.info(
                "[JOB] Acesso revogado por expiração",
                extra={"user_id": sub["user_id"], "sub_id": sub["id"]},
            )
        except Exception:
            logger.exception(
                "[JOB] Falha ao remover usuário expirado do grupo",
                extra={"telegram_id": telegram_id},
            )

from app.infra import db

async def schedule_expiration_reminders_job():
    """
    Job que roda periodicamente e popula a outbox com avisos de 24h.
    """
    db.schedule_expiration_reminders(hours=24)

