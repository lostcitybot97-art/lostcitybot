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

application = build_application()


@app.on_event("startup")
async def startup():
    db.init_db()

    if not config.WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL não definida no ambiente")

    await application.initialize()
    await application.start()  # ✅ CORREÇÃO IMPORTANTE
    await application.bot.set_webhook(config.WEBHOOK_URL)

    logger.info("Telegram application inicializada (webhook mode)")


@app.on_event("shutdown")
async def shutdown():
    await application.stop()      # ✅ CORREÇÃO IMPORTANTE
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
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    data_id = (payload.get("data") or {}).get("id")
    if not data_id:
        data_id = request.query_params.get("data.id")

    event_type = payload.get("type") or request.query_params.get("type")

    logger.info(f"Webhook Mercado Pago recebido: data_id={data_id} type={event_type}")

    if not data_id or event_type != "payment":
        return {"status": "ignored"}

    payment = db.get_payment_by_gateway_id(str(data_id))
    if not payment:
        logger.warning(f"Pagamento {data_id} nao encontrado no banco")
        return {"status": "not_found"}

    status = check_payment_status(str(data_id))

    if not status:
        return {"status": "error_checking"}

    db.update_payment_status(payment_id=payment["id"], status=status)
    logger.info(f"Pagamento {payment['id']} atualizado para {status}")

    if status == "approved":

        # Buscar o usuário completo para obter o telegram_id
        user = get_user_by_id(payment["user_id"])
        if not user:
            logger.warning(f"Usuario {payment['user_id']} nao encontrado para pagamento {payment['id']}")
            return {"status": "user_not_found"}

        telegram_id = user["telegram_id"]

        try:
            # Cria link de convite para o grupo, válido por 1 hora e 1 uso
            expire_date = int(time.time()) + 3600  # 1 hora
            invite_link = await application.bot.create_chat_invite_link(
                chat_id=config.GRUPO_ID,
                member_limit=1,
                expire_date=expire_date,
            )

            text = (
                "✅ Pagamento aprovado!\n\n"
                "Aqui está seu link de acesso ao grupo:\n"
                f"{invite_link.invite_link}\n\n"
                "Ele é válido por 1 hora e para apenas uma entrada."
            )

            await application.bot.send_message(
                chat_id=telegram_id,
                text=text,
            )
        except Exception as e:
            logger.warning(f"Erro ao criar/enviar invite para usuario {telegram_id}: {e}")

    return {"status": "ok"}


        user = get_user_by_id(payment["user_id"])
        if not user:
            logger.warning(
                f"Usuario {payment['user_id']} nao encontrado para pagamento {payment['id']}"
            )
            return {"status": "user_not_found"}

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
                "Aqui está seu link de acesso ao grupo:\n"
                f"{invite_link.invite_link}\n\n"
                "Ele é válido por 1 hora e para apenas uma entrada."
            )

            await application.bot.send_message(
                chat_id=telegram_id,
                text=text,
            )

        except Exception as e:
            logger.warning(
                f"Erro ao criar/enviar invite para usuario {telegram_id}: {e}"
            )

    return {"status": "ok"}

