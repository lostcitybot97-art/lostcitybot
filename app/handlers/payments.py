import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler
from app.infra import db
from app.payments import create_pix_payment, check_payment_status
from app.domain.plans import get_plan

logger = logging.getLogger(__name__)


async def handle_buy_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plan_id = query.data.split(":")[1]
    plan_data = get_plan(plan_id)
    if not plan_data:
        await query.edit_message_text("❌ Plano inválido.")
        return

    user_id = db.get_or_create_user(
        telegram_id=query.from_user.id,
        nome=query.from_user.first_name,
    )

    await query.edit_message_text("⏳ Gerando seu PIX...")

    try:
        payment = create_pix_payment(user_id=user_id, plan=plan_id)
    except Exception:
        logger.exception("Erro ao gerar PIX")
        await query.edit_message_text("❌ Erro ao gerar PIX. Tente novamente com /start")
        return

    qr_code = payment["point_of_interaction"]["transaction_data"]["qr_code"]

    await query.edit_message_text(
        f"✅ *{plan_data['title']} — R$ {plan_data['price']:.2f}*\n\n"
        f"Pague via PIX copia e cola:\n\n"
        f"`{qr_code}`\n\n"
        f"⏱ Expira em 30 minutos.\n"
        f"Após pagar, clique em Verificar Pagamento.",
        parse_mode="Markdown",
        reply_markup=__check_button(),
    )


def __check_button():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔍 Verificar Pagamento", callback_data="check_payment_status")
    ]])


async def handle_check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = db.get_or_create_user(
        telegram_id=query.from_user.id,
        nome=query.from_user.first_name,
    )
    pending = db.get_pending_payment(user_id)

    if not pending:
        await query.edit_message_text("❌ Nenhum pagamento pendente encontrado.\n\nGere um novo: /start")
        return

    status = check_payment_status(pending["gateway_payment_id"])

    if status == "approved":
        await query.edit_message_text("✅ *Pagamento confirmado!*\n\nSeu acesso será liberado.", parse_mode="Markdown")
    elif status in ("pending", "in_process"):
        await query.message.reply_text("⏳ *Pagamento ainda pendente.*\n\nTente novamente em instantes.", parse_mode="Markdown")
    elif status in ("cancelled", "rejected", "expired"):
        await query.message.reply_text("❌ *PIX expirou ou foi cancelado.*\n\nGere um novo: /start", parse_mode="Markdown")
    else:
        await query.message.reply_text(f"❓ Status: {status}", parse_mode="Markdown")


def register_handlers(application):
    application.add_handler(CallbackQueryHandler(handle_buy_plan, pattern="^buy:"))
    application.add_handler(CallbackQueryHandler(handle_check_payment_status, pattern="^check_payment_status$"))
