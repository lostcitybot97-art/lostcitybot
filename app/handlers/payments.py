import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler
from app.infra import db
from app.payments import check_payment_status

logger = logging.getLogger(__name__)


async def handle_check_payment_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handler para verificar status de pagamento PIX"""
    query = update.callback_query
    await query.answer()

    user_id = db.get_or_create_user(query.from_user.id)
    pending = db.get_pending_payment(user_id)

    if not pending:
        await query.edit_message_text(
            "❌ Nenhum pagamento pendente encontrado.\n\n"
            "Se precisar, gere um novo Pix."
        )
        return

    external_reference = pending["external_reference"]
    status = check_payment_status(external_reference)

    if not status:
        await query.edit_message_text(
            "⚠️ Não foi possível verificar o pagamento agora.\n\n"
            "Tente novamente em alguns instantes."
        )
        return

    # Status: approved
    if status == "approved":
        try:
            await query.edit_message_text(
                "✅ *Pagamento confirmado!*\n\n"
                "Seu acesso será liberado automaticamente.",
                parse_mode="Markdown",
            )
        except BadRequest:
            # Mensagem tem foto, envia nova mensagem
            await query.message.reply_text(
                "✅ *Pagamento confirmado!*\n\n"
                "Seu acesso será liberado automaticamente.",
                parse_mode="Markdown",
            )
        return

    # Status: pending
    if status in ("pending", "in_process"):
        try:
            await query.edit_message_text(
                "⏳ *Pagamento ainda pendente*\n\n"
                "Você pode verificar novamente em alguns instantes.",
                parse_mode="Markdown",
            )
        except BadRequest:
            await query.message.reply_text(
                "⏳ *Pagamento ainda pendente*\n\n"
                "Você pode verificar novamente em alguns instantes.",
                parse_mode="Markdown",
            )
        return

    # Status: cancelled/rejected/expired
    if status in ("cancelled", "rejected", "expired"):
        try:
            await query.edit_message_text(
                "❌ *Pagamento não concluído*\n\n"
                "Este Pix expirou ou foi cancelado.\n"
                "Por favor, gere um novo pagamento: /start",
                parse_mode="Markdown",
            )
        except BadRequest:
            await query.message.reply_text(
                "❌ *Pagamento não concluído*\n\n"
                "Este Pix expirou ou foi cancelado.\n"
                "Por favor, gere um novo pagamento: /start",
                parse_mode="Markdown",
            )
        return

    # Status desconhecido
    try:
        await query.edit_message_text(
            f"❓ *Status desconhecido:* {status}",
            parse_mode="Markdown",
        )
    except BadRequest:
        await query.message.reply_text(
            f"❓ *Status desconhecido:* {status}",
            parse_mode="Markdown",
        )

def register_handlers(application):
    application.add_handler(
        CallbackQueryHandler(
            handle_check_payment_status,
            pattern="^check_payment_status$",
        )
    )
