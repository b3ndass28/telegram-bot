from helpers import list_allowed_users


async def broadcast_cmd(update, context, require_owner):
    if not await require_owner(update, context):
        return
    context.user_data["mode"] = "awaiting_broadcast"
    await update.message.reply_text("📢 Отправь сообщение, которое нужно разослать всем allowed users.")


async def handle_broadcast_text(update, context, text, is_owner):
    if context.user_data.get("mode") != "awaiting_broadcast":
        return False

    if not is_owner(update.effective_user.id):
        return True

    ok = 0
    fail = 0
    for uid in list_allowed_users().keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 Сообщение от owner:\n\n{text}")
            ok += 1
        except Exception:
            fail += 1

    context.user_data.pop("mode", None)
    await update.message.reply_text(f"✅ Broadcast готов.\n\nОтправлено: {ok}\nНе доставлено: {fail}")
    return True
