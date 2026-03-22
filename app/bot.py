from telegram.ext import ApplicationBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import TELEGRAM_TOKEN
from app.handlers import payments, start, subscriptions
from app.jobs import (
    process_confirmed_payments,
    revoke_expired_group_access,
    schedule_expiration_reminders_job,
    process_outbox_tasks,  
)


def build_application():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Handlers
    start.register_handlers(application)
    payments.register_handlers(application)
    subscriptions.register_handlers(application)

    # Jobs
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        process_confirmed_payments,
        "interval",
        minutes=1,
    )
    scheduler.add_job(
        revoke_expired_group_access,
        "interval",
        minutes=5,
        args=[application],
    )
    scheduler.add_job(
        schedule_expiration_reminders_job,
        "interval",
        minutes=30,
    )
    scheduler.add_job(
        process_outbox_tasks,
        "interval",
        minutes=1,
        args=[application],
    )



    scheduler.start()

    return application

