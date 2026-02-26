from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes
from app.infra import db
from app.domain.plans import PLANS

def plans_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=f"{data['title']} - R${data['price']:.2f}",
            callback_data=f"buy:{plan}"
        )]
        for plan, data in PLANS.items()
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(telegram_id=user.id, nome=user.full_name)
    await update.message.reply_text(
        "👋 Bem-vindo! Escolha um plano abaixo:",
        parse_mode="Markdown",
        reply_markup=plans_keyboard(),
    )

def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
