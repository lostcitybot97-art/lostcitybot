from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes

from app.infra import db
from app.domain.plans import PLANS

# 🔥 DESCONTOS
DISCOUNTS = {
    "semanal": 0.25,  # 25%
    "mensal": 0.35,   # 35%
}


def get_discounted_price(plan_id: str):
    base_price = PLANS[plan_id]["price"]
    discount = DISCOUNTS.get(plan_id, 0)

    final_price = round(base_price * (1 - discount), 2)

    return base_price, final_price, int(discount * 100)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    semanal_base, semanal_final, sem_desc = get_discounted_price("semanal")
    mensal_base, mensal_final, men_desc = get_discounted_price("mensal")

    rows = [
        [
            InlineKeyboardButton(
                text=f"🗓 Semanal ~R${semanal_base:.2f}~ → R${semanal_final:.2f} ({sem_desc}% OFF)",
                callback_data="buy:semanal",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📆 Mensal ~R${mensal_base:.2f}~ → R${mensal_final:.2f} ({men_desc}% OFF)",
                callback_data="buy:mensal",
            )
        ],
        [
            InlineKeyboardButton("📄 Minha assinatura", callback_data="menu:minha_assinatura"),
            InlineKeyboardButton("🧾 Histórico", callback_data="menu:historico"),
        ],
        [
            InlineKeyboardButton("🔁 Renovar plano", callback_data="menu:renovar"),
            InlineKeyboardButton("🆘 Suporte", callback_data="menu:suporte"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(telegram_id=user.id, nome=user.full_name)

    text = (
        "👋 *Bem-vindo ao LostCityBot!*\n\n"
        "🔥 *Desconto ativo por tempo limitado*\n"
        "🚀 Acesso imediato ao conteúdo\n\n"
        "Escolha seu plano abaixo:"
    )

    keyboard = main_menu_keyboard()

    # /start digitado no chat
    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # /start disparado a partir de callback (ex.: botão "Voltar ao menu")
    if update.callback_query:
        query = update.callback_query
        message = query.message

        current_text = (message.text or "").strip()
        current_markup = message.reply_markup

        # ✅ evita BadRequest: Message is not modified
        if current_text == text and current_markup == keyboard:
            return

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
