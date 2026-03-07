import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from app.infra import db
from app.handlers.start import start  # para usar como "voltar ao menu"

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
        # reusa o /start como menu principal
        await start(update, context)
    elif query.data == "menu:renovar":
        await query.edit_message_text(
            "🔁 Para renovar, escolha um novo plano no menu principal.",
            reply_markup=back_menu_keyboard(),
        )
    elif query.data == "menu:suporte":
        await query.edit_message_text(
            "🆘 Suporte: fale com @seu_usuario_ou_canal.",
            reply_markup=back_menu_keyboard(),
        )


def register_handlers(application):
    application.add_handler(CommandHandler("minha_assinatura", minha_assinatura))
    application.add_handler(CommandHandler("historico", historico))
    application.add_handler(CallbackQueryHandler(menu_minhas_coisas, pattern="^menu:"))

