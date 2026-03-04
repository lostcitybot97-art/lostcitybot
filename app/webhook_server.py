import logging
import time

from fastapi import FastAPI, Request, HTTPException
from telegram import Update

from app.bot import build_application
from app.infra import db
from app import config
from app.payments import check_payment_status
from app.infra.db import confirm_payment, get_user_by_id
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

@app.api_route("/health", methods=["GET", "HEAD"])
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

        # 3️⃣ Ativa / empilha assinatura (idempotente)
        activate_subscription_from_payment(payment["id"])

        logger.info(
            "Pagamento confirmado e assinatura ativada",
            extra={"gateway_payment_id": gateway_payment_id},
        )

        # 4️⃣ Envia link de convite para o usuário
        user = get_user_by_id(payment["user_id"])
        if not user:
            logger.warning(
                "Usuario nao encontrado para pagamento",
                extra={"user_id": payment["user_id"], "payment_id": payment["id"]},
            )
            return {"ok": True}

        telegram_id = user["telegram_id"]

        try:
            expire_date = int(time.time()) + 3600

            invite_link = await application.bot.create_chat_invite_link(
                chat_id=config.GRUPO_ID,
                member_limit=1,
                expire_date=expire_date,
            )

            text = (
                "✅ Pagamento aprovado!\n\n"
                "Aqui está seu link EXCLUSIVO de acesso ao grupo:\n"
                f"{invite_link.invite_link}\n\n"
                "Este link é válido por 1 hora e pode ser usado apenas uma vez. "
                "Não compartilhe com outras pessoas."
            )

            await application.bot.send_message(
                chat_id=telegram_id,
                text=text,
            )

            await application.bot.send_message(
                chat_id=telegram_id,
                text=text,
            )

            logger.info(
                "Invite enviado com sucesso para usuario",
                extra={"telegram_id": telegram_id, "payment_id": payment["id"]},
            )

        except Exception as e:
            logger.warning(
                "Erro ao criar/enviar invite para usuario",
                extra={"telegram_id": telegram_id, "error": str(e)},
            )

    except Exception:
        logger.exception("Erro no webhook MercadoPago")
        raise HTTPException(status_code=500, detail="Erro MP")

    return {"ok": True}

