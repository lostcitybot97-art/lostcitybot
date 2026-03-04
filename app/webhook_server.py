import logging
import time

from fastapi import FastAPI, Request, HTTPException
from telegram import Update

from app.bot import build_application
from app.infra import db
from app.infra.db import get_user_by_id
from app import config
from app.payments import check_payment_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

app = FastAPI()

application = None  # 👈 não cria aqui


@app.on_event("startup")
async def startup():
    global application

    db.init_db()

    if not config.WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL não definida no ambiente")

    application = build_application()

    await application.initialize()
    await application.start()

    await application.bot.delete_webhook(drop_pending_updates=True)

    await application.bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
    )

    logger.info(f"Webhook configurado para {config.WEBHOOK_URL}")
    logger.info("Telegram application inicializada (webhook mode)")


@app.on_event("shutdown")
async def shutdown():
    if application:
        await application.stop()
        await application.shutdown()
        logger.info("Telegram application finalizada")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    global application

    payload = await request.json()

    try:
        update = Update.de_json(payload, application.bot)
        await application.process_update(update)
    except Exception:
        logger.exception("Erro ao processar update do Telegram")
        raise HTTPException(status_code=500, detail="Erro Telegram")

    return {"ok": True}
