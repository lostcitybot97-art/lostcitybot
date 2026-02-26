from telegram.ext import ApplicationBuilder

from app.config import TELEGRAM_TOKEN
from app.handlers import payments
from app.handlers import start


def build_application():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    start.register_handlers(application)
    payments.register_handlers(application)

    return application
