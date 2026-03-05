# app/handlers/subscriptions.py
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from app.infra import db

logger = logging.getLogger(__name__)


async def minha_assinatura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Garante que o usuário existe na tabela users e pega o id interno
    user_id = db.get_or_create_user(telegram_id=user.id, nome=user.full_name)

    sub = db.get_active_subscription_with_days(user_id)

    if not sub:
        await update.message.reply_text(
            "Você não tem nenhuma assinatura ativa no momento."
        )
        return

    plan = sub["plan"]
    starts_at = sub["starts_at"]
    ends_at = sub["ends_at"]
    dias_restantes = int(sub["dias_restantes"])

    # (Opcional) formata datas de ISO para algo mais amigável
    try:
        starts_dt = datetime.fromisoformat(starts_at)
        ends_dt = datetime.fromisoformat(ends_at)
        starts_str = starts_dt.strftime("%d/%m/%Y %H:%M")
        ends_str = ends_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        # Se der qualquer problema de parse, manda o bruto mesmo
        starts_str = starts_at
        ends_str = ends_at

    text = (
        "📄 *Sua assinatura*\n\n"
        f"Plano: `{plan}`\n"
        f"Início: `{starts_str}`\n"
        f"Fim: `{ends_str}`\n"
        f"Dias restantes: *{dias_restantes}*"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


def register_handlers(application):
    application.add_handler(CommandHandler("minha_assinatura", minha_assinatura))

