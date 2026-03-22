import logging
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

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
    payments = db.get_confirmed_unprocessed_payments()

    logger.info(f"[DEBUG] Pagamentos encontrados: {len(payments)}")

    for payment in payments:
        logger.info(f"[DEBUG] Payment raw: {payment}")

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
    Job que roda periodicamente e popula a outbox com avisos D-3, D-2 e D-1.
    """
    db.schedule_expiration_reminders()

async def process_outbox_tasks(application):
    """
    Consome tasks da outbox de aviso de expiração (D-3, D-2, D-1)
    e envia mensagem no Telegram com botão de renovação.
    """
    with db.get_db() as conn:
        cur = conn.cursor()

        # 1) Buscar tasks pendentes
        cur.execute(
            """
            SELECT
                ot.id,
                ot.user_id,
                ot.metadata,
                u.telegram_id
            FROM outbox_tasks ot
            JOIN users u ON u.id = ot.user_id
            WHERE
                ot.status = 'pending'
                AND ot.task_type = 'SUBSCRIPTION_EXPIRY_WARNING'
            ORDER BY ot.created_at
            LIMIT 50
            """
        )
        rows = cur.fetchall()

        if not rows:
            return

        for task_id, user_id, metadata, telegram_id in rows:
            # metadata pode vir como dict ou string json
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            subscription_id = metadata.get("subscription_id")
            plan = metadata.get("plan")
            days_left = int(metadata.get("days_left", 0))

            logger.info(
                "[OUTBOX] Processando aviso de expiração",
                extra={
                    "task_id": task_id,
                    "user_id": user_id,
                    "telegram_id": telegram_id,
                    "subscription_id": subscription_id,
                    "plan": plan,
                    "days_left": days_left,
                },
            )

            if days_left == 3:
                text = (
                    "⚠️ Sua assinatura está entrando na reta final.\n\n"
                    f"Plano: {plan}\n"
                    "Vence em 3 dias.\n\n"
                    "Renove agora e garanta um desconto especial."
                )
            elif days_left == 2:
                text = (
                    "⚠️ Sua assinatura vence em 2 dias.\n\n"
                    f"Plano: {plan}\n\n"
                    "Ainda dá tempo de renovar com desconto."
                )
            elif days_left == 1:
                text = (
                    "⏰ Sua assinatura vence amanhã.\n\n"
                    f"Plano: {plan}\n\n"
                    "Renove agora com desconto para não perder o acesso."
                )
            else:
                text = (
                    f"Aviso de expiração de assinatura.\n\n"
                    f"Plano: {plan}\n"
                    f"Dias restantes: {days_left}"
                )

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔁 Renovar com desconto",
                        callback_data=f"renew_sub:{subscription_id}:{days_left}",
                    )
                ]
            ])

            try:
                await application.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    reply_markup=keyboard,
                )
            except TelegramError:
                logger.exception(
                    "[OUTBOX] Falha ao enviar aviso de expiração",
                    extra={"task_id": task_id, "telegram_id": telegram_id},
                )
                cur.execute(
                    "UPDATE outbox_tasks SET status = 'error', processed_at = NOW() WHERE id = %s",
                    (task_id,),
                )
                continue

            cur.execute(
                """
                UPDATE outbox_tasks
                SET status = 'processed',
                    processed_at = NOW()
                WHERE id = %s
                """,
                (task_id,),
            )

