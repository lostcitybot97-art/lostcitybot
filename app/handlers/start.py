from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes
from app.infra import db
from app.domain.plans import PLANS


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        # linha 1: planos
        [
            InlineKeyboardButton(
                text=f"🗓 Plano semanal - R${PLANS['semanal']['price']:.2f}",
                callback_data="buy:semanal",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📆 Plano mensal - R${PLANS['mensal']['price']:.2f}",
                callback_data="buy:mensal",
            )
        ],
        # linha 2: painel
        [
            InlineKeyboardButton("📄 Minha assinatura", callback_data="menu:minha_assinatura"),
            InlineKeyboardButton("🧾 Histórico", callback_data="menu:historico"),
        ],
        # linha 3: ações extra
        [
            InlineKeyboardButton("🔁 Renovar plano", callback_data="menu:renovar"),
            InlineKeyboardButton("🆘 Suporte", callback_data="menu:suporte"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(telegram_id=user.id, nome=user.full_name)

    text = (
        "👋 *Bem-vindo ao LostCityBot!*\n\n"
        "Use o menu abaixo para:\n"
        "• Escolher ou renovar seu plano\n"
        "• Ver sua assinatura atual\n"
        "• Consultar seu histórico de pagamentos\n"
        "• Falar com o suporte\n\n"
        "_Basta tocar nos botões, não precisa digitar comandos._"
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
    elif update.callback_query:
        # usado quando clicamos em 🔙 Voltar ao menu
        query = update.callback_query
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )


def register_handlers(application):
    application.add_handler(CommandHandler("start", start))

