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

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    elif update.callback_query:
        query = update.callback_query

        # ✅ só tenta editar se algo REALMENTE mudou
        current_text = (query.message.text or "").strip()
        if current_text == text and query.message.reply_markup == keyboard:
            # Já estamos nesse menu; não faz nada
            return

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
