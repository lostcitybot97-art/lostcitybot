import logging

from fastapi import FastAPI, Request, HTTPException
from telegram import Update

from app.bot import build_application
from app.infra import db
from app import config
from app.payments import check_payment_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

app = FastAPI()

application = build_application()


@app.on_event("startup")
async def startup():
    db.init_db()
    await application.initialize()
    await application.bot.set_webhook(config.WEBHOOK_URL)
    logger.info("Telegram application inicializada (webhook mode)")


@app.on_event("shutdown")
async def shutdown():
    await application.shutdown()
    logger.info("Telegram application finalizada")


@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    payload = await request.json()

    try:
        update = Update.de_json(payload, application.bot)
        await application.process_update(update)
    except Exception:
        logger.exception("Erro ao processar update do Telegram")
        raise HTTPException(status_code=500, detail="Erro Telegram")

    return {"ok": True}


@app.post("/webhook/mercadopago")
async def mercadopago_webhook(request: Request):
    payload = await request.json()

    logger.info("Webhook Mercado Pago recebido")

    data_id = payload.get("data", {}).get("id")
    event_type = payload.get("type")

    if not data_id or event_type != "payment":
        return {"status": "ignored"}

    payment = db.get_payment_by_gateway_id(data_id)
    if not payment:
        logger.warning("Pagamento não encontrado no banco")
        return {"status": "not_found"}

    external_reference = payment["external_reference"]
    status = check_payment_status(external_reference)

    if not status:
        raise HTTPException(status_code=400, detail="Erro ao consultar status")

    db.update_payment_status(
        payment_id=payment["id"],
        status=status,
    )

    logger.info(
        "Pagamento atualizado",
        extra={
            "payment_id": payment["id"],
            "status": status,
        },
    )

    return {"status": "ok"}
