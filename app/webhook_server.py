import logging

from fastapi import FastAPI, Request, HTTPException
from telegram import Update

from app.bot import build_application
from app.infra import db
from app import config
from app.payments import check_payment_status
from app.infra.db import confirm_payment
from app.domain.subscriptions import activate_subscription_from_payment


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

app = FastAPI()

application = None  # Telegram Application (webhook mode)


# =========================
# STARTUP / SHUTDOWN
# =========================

@app.on_event("startup")
async def startup():
    global application

    logger.info("Inicializando aplicação...")

    # Inicializa banco (cria tabelas se não existirem)
    db.init_db()

    if not config.WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL não definida no ambiente")

    # Cria aplicação do Telegram
    application = build_application()

    await application.initialize()
    await application.start()

    # Remove webhook anterior
    await application.bot.delete_webhook(drop_pending_updates=True)

    # Define novo webhook
    await application.bot.set_webhook(
        url=config.WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
    )

    logger.info(f"Webhook Telegram configurado para {config.WEBHOOK_URL}")
    logger.info("Telegram application inicializada (modo webhook)")


@app.on_event("shutdown")
async def shutdown():
    if application:
        await application.stop()
        await application.shutdown()
        logger.info("Telegram application finalizada")


# =========================
# HEALTHCHECK
# =========================

@app.get("/health")
async def health():
    return {"status": "ok"}


# =========================
# TELEGRAM WEBHOOK
# =========================

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


# =========================
# MERCADOPAGO WEBHOOK
# =========================

@app.post("/webhook/mercadopago")
async def mercadopago_webhook(request: Request):
    payload = await request.json()

    logger.info("Webhook MercadoPago recebido", extra={"payload": payload})

    try:
        # Apenas eventos de pagamento
        if payload.get("type") != "payment":
            return {"ok": True}

        data = payload.get("data", {})
        gateway_payment_id = data.get("id")

        if not gateway_payment_id:
            logger.warning("Webhook MP sem payment id")
            return {"ok": True}

        # 1️⃣ Confere status direto no MercadoPago
        status = check_payment_status(gateway_payment_id)

        if status != "approved":
            logger.info(
                "Pagamento ainda não aprovado",
                extra={"gateway_payment_id": gateway_payment_id, "status": status},
            )
            return {"ok": True}

        # 2️⃣ Marca pagamento como confirmado no banco
        payment = confirm_payment(gateway_payment_id)

        # 3️⃣ Ativa / empilha assinatura
        activate_subscription_from_payment(payment["id"])

        logger.info(
            "Pagamento confirmado e assinatura ativada",
            extra={"gateway_payment_id": gateway_payment_id},
        )

    except Exception:
        logger.exception("Erro no webhook MercadoPago")
        raise HTTPException(status_code=500, detail="Erro MP")

    return {"ok": True}
