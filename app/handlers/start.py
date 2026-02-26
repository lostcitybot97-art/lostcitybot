from telegram import Update
from telegram.ext import ContextTypes, CommandHandler


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Bot online!\n\nSeu webhook está funcionando."
    )


def register_handlers(application):
    application.add_handler(CommandHandler("start", start_command))
