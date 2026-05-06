
import logging

from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

from app.infra import db
from app.payments import create_pix_payment, check_payment_status
from app.domain.plans import get_plan

# 🔥 puxando cálculo de desconto
from app.handlers.start import get_discounted_price

import base64
from io import BytesIO

logger = logging.getLogger(__name__)


async def handle_buy_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plan_id = query.data.split(":")[1]
    plan_data = get_plan(plan_id)

    if not plan_data:
        await query.edit_message_text("❌ Plano inválido.")
        return

    # 🔥 calcula desconto corretamente
    base_price, final_price, discount_percent = get_discounted_price(plan_id)

    user_id = db.get_or_create_user(
        telegram_id=query.from_user.id,
        nome=query.from_user.first_name,
    )

    await query.edit_message_text("⏳ Gerando seu PIX...")

    try:
        # 🔥 AQUI É O PONTO CRÍTICO — usa valor com desconto
        payment = create_pix_payment(
            user_id=user_id,
            plan=plan_id,
            override_amount=final_price,
        )
    except Exception:
        logger.exception("Erro ao gerar PIX")
        await query.edit_message_text("❌ Erro ao gerar PIX. Tente novamente com /start")
        return

    transaction_data = payment["point_of_interaction"]["transaction_data"]
    qr_code = transaction_data["qr_code"]
    qr_base64 = transaction_data.get("qr_code_base64")

    # 🔥 TEXTO COERENTE COM DESCONTO
    caption_text = (
        f"🔥 *{plan_data['title']}*\n"
        f"De ~R$ {base_price:.2f}~ por *R$ {final_price:.2f}* ({discount_percent}% OFF)\n\n"
        f"Pague via PIX copia e cola:\n\n"
        f"`{qr_code}`\n\n"
        f"⏱ Expira em 30 minutos.\n"
        f"Após pagar, clique em Verificar Pagamento."
    )

    if qr_base64:
        qr_bytes = base64.b64decode(qr_base64)
        bio = BytesIO(qr_bytes)
        bio.name = "qrcode.png"

        await query.message.reply_photo(
            photo=bio,
            caption=caption_text,
            parse_mode="Markdown",
            reply_markup=__check_button(),
        )
    else:
        await query.message.reply_text(
            caption_text,
            parse_mode="Markdown",
            reply_markup=__check_button(),
        )


def __check_button():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔍 Verificar Pagamento",
                callback_data="check_payment_status"
            )
        ]
    ])


async def handle_check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = db.get_or_create_user(
        telegram_id=query.from_user.id,
        nome=query.from_user.first_name,
    )

    pending = db.get_pending_payment(user_id)

    if not pending:
        await query.message.reply_text(
            "❌ Nenhum pagamento pendente encontrado.\n\nGere um novo: /start"
        )
        return

    status = check_payment_status(pending["gateway_payment_id"])

    if status == "approved":
        await query.message.reply_text(
            "✅ *Pagamento confirmado!*\n\nSeu acesso será liberado.",
            parse_mode="Markdown",
        )

    elif status in ("pending", "in_process"):
        await query.message.reply_text(
            "⏳ *Pagamento ainda pendente.*\n\nTente novamente em instantes.",
            parse_mode="Markdown",
        )

    elif status in ("cancelled", "rejected", "expired"):
        await query.message.reply_text(
            "❌ *PIX expirou ou foi cancelado.*\n\nGere um novo: /start",
            parse_mode="Markdown",
        )

    else:
        await query.message.reply_text(
            f"❓ Status: {status}",
            parse_mode="Markdown",
        )


def register_handlers(application):
    application.add_handler(
        CallbackQueryHandler(handle_buy_plan, pattern="^buy:")
    )
    application.add_handler(
        CallbackQueryHandler(handle_check_payment_status, pattern="^check_payment_status$")
    )
