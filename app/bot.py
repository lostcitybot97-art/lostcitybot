from telegram.ext import ApplicationBuilder

from app.config import TELEGRAM_TOKEN
from app.handlers import payments, start, subscriptions


def build_application():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Handlers existentes
    start.register_handlers(application)
    payments.register_handlers(application)

    # Novo handler: /minha_assinatura
    subscriptions.register_handlers(application)

    return application

