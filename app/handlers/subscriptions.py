import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from app.infra import db
from app.handlers.start import start  # para usar como "voltar ao menu"
from app.domain.plans import get_plan
from app.payments import create_pix_payment

import base64
from io import BytesIO

SUPORTE_USERNAME = "SuporteVendasLC"
SUPORTE_LINK = f"https://t.me/SuporteVendasLC"

logger = logging.getLogger(__name__)


def back_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Voltar ao menu", callback_data="menu:voltar")],
    ])


async def minha_assinatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = db.get_or_create_user(telegram_id=user.id, nome=user.full_name)
    sub = db.get_active_subscription_with_days(user_id)

    if not sub:
        text = "Você não tem nenhuma assinatura ativa no momento."
        if update.message:
            await update.message.reply_text(text, reply_markup=back_menu_keyboard())
        else:
            await update.callback_query.edit_message_text(
                text, reply_markup=back_menu_keyboard()
            )
        return

    plan = sub["plan"]
    starts_at = sub["starts_at"]
    ends_at = sub["ends_at"]
    dias_restantes = int(sub["dias_restantes"])

    try:
        starts_dt = datetime.fromisoformat(starts_at)
        ends_dt = datetime.fromisoformat(ends_at)
        starts_str = starts_dt.strftime("%d/%m/%Y %H:%M")
        ends_str = ends_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        starts_str = starts_at
        ends_str = ends_at

    text = (
        "📄 *Sua assinatura*\n\n"
        f"Plano: `{plan}`\n"
        f"Início: `{starts_str}`\n"
        f"Fim: `{ends_str}`\n"
        f"Dias restantes: *{dias_restantes}*"
    )

    if update.message:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=back_menu_keyboard()
        )
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=back_menu_keyboard()
        )


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = db.get_or_create_user(telegram_id=user.id, nome=user.full_name)
    rows = db.get_payments_history_by_user(user_id, limit=10)

    if not rows:
        text = "Você ainda não tem pagamentos registrados."
        if update.message:
            await update.message.reply_text(text, reply_markup=back_menu_keyboard())
        else:
            await update.callback_query.edit_message_text(
                text, reply_markup=back_menu_keyboard()
            )
        return

    linhas = []
    for p in rows:
        try:
            created_dt = datetime.fromisoformat(p["created_at"])
            created_str = created_dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            created_str = p["created_at"]

        status = p["status"]
        plan = p["plan"]
        amount = p["amount"]

        linha = f"- {created_str} | plano `{plan}` | R${amount:.2f} | status `{status}`"
        linhas.append(linha)

    texto = "🧾 *Seus últimos pagamentos:*\n\n" + "\n".join(linhas)

    if update.message:
        await update.message.reply_text(
            texto, parse_mode="Markdown", reply_markup=back_menu_keyboard()
        )
    else:
        await update.callback_query.edit_message_text(
            texto, parse_mode="Markdown", reply_markup=back_menu_keyboard()
        )


async def menu_minhas_coisas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu:minha_assinatura":
        await minha_assinatura(update, context)
    elif query.data == "menu:historico":
        await historico(update, context)
    elif query.data == "menu:voltar":
        await start(update, context)
    elif query.data == "menu:renovar":
        user = update.effective_user
        user_id = db.get_or_create_user(telegram_id=user.id, nome=user.full_name)

        sub = db.get_active_subscription_with_days(user_id)
        if not sub:
            # Não é membro ativo → manda pro menu normal
            await start(update, context)
            return

        plan_id = sub["plan"]
        dias_restantes = int(sub["dias_restantes"])

        plan_data = get_plan(plan_id)
        if not plan_data:
            await query.edit_message_text(
                "❌ Não foi possível identificar seu plano atual. Use o menu principal para escolher um plano.",
                reply_markup=back_menu_keyboard(),
            )
            return

        base_price = plan_data["price"]
        discount_percent = 0

        # Janela de renovação com desconto: até 3 dias restantes
        if dias_restantes <= 3:
            discount_percent = plan_data.get("renewal_discount_percent", 0)

        final_price = base_price
        if discount_percent > 0:
            final_price = round(base_price * (1 - discount_percent / 100), 2)

        await query.edit_message_text("⏳ Gerando seu PIX para renovação...")

        try:
            payment = create_pix_payment(
                user_id=user_id,
                plan=plan_id,
                override_amount=final_price,
            )
        except Exception:
            logger.exception("Erro ao gerar PIX de renovação")
            await query.edit_message_text(
                "❌ Erro ao gerar PIX. Tente novamente com /start",
                reply_markup=back_menu_keyboard(),
            )
            return

        transaction_data = payment["point_of_interaction"]["transaction_data"]
        qr_code = transaction_data["qr_code"]
        qr_base64 = transaction_data.get("qr_code_base64")

        caption_text = (
            f"✅ *Renovação — {plan_data['title']}*\n"
            f"Valor oficial do plano: R$ {base_price:.2f}\n"
        )

        if discount_percent > 0:
            caption_text += (
                f"Desconto de renovação: {discount_percent}%\n"
                f"Valor promocional: *R$ {final_price:.2f}*\n"
            )

        caption_text += (
            "\nPague via PIX copia e cola:\n\n"
            f"`{qr_code}`\n\n"
            "⏱ Expira em 30 minutos.\n"
            "Após pagar, clique em *Verificar Pagamento*."
        )

        check_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔍 Verificar Pagamento", callback_data="check_payment_status")
        ]])

        if qr_base64:
            qr_bytes = base64.b64decode(qr_base64)
            bio = BytesIO(qr_bytes)
            bio.name = "qrcode.png"

            await query.message.reply_photo(
                photo=bio,
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=check_markup,
            )
        else:
            await query.message.reply_text(
                caption_text,
                parse_mode="Markdown",
                reply_markup=check_markup,
            )
    elif query.data == "menu:suporte":
        text = (
            "🆘 *Suporte LostCityBot*\n\n"
            "Fale diretamente com nosso time de suporte no Telegram:\n"
            f"{SUPORTE_LINK}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_menu_keyboard(),
            disable_web_page_preview=True,
        )


def register_handlers(application):
    application.add_handler(CommandHandler("minha_assinatura", minha_assinatura))
    application.add_handler(CommandHandler("historico", historico))
    application.add_handler(CallbackQueryHandler(menu_minhas_coisas, pattern="^menu:"))

