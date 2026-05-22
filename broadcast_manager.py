import json
from pathlib import Path

from config import SETTINGS_FILE


def _load_settings():
    path = Path(SETTINGS_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def _extract_allowed_users(settings):
    """
    Supports different settings.json structures used in previous bot versions.
    Returns a dict/list-like collection of allowed Telegram user IDs.
    """
    if not isinstance(settings, dict):
        return {}

    # Most common structure:
    # {"users": {"123": {...}, "456": {...}}}
    users = settings.get("users")
    if isinstance(users, dict):
        return users

    # Alternative structures:
    # {"allowed_users": {"123": {...}}}
    allowed = settings.get("allowed_users")
    if isinstance(allowed, dict):
        return allowed

    # {"allowed_users": [123, 456]}
    if isinstance(allowed, list):
        return {str(uid): {} for uid in allowed}

    # {"authorized_users": [123, 456]}
    authorized = settings.get("authorized_users")
    if isinstance(authorized, list):
        return {str(uid): {} for uid in authorized}

    return {}


async def broadcast_cmd(update, context, require_owner):
    if not await require_owner(update, context):
        return

    context.user_data["mode"] = "awaiting_broadcast"
    await update.message.reply_text(
        "📢 Отправь сообщение, которое нужно разослать всем allowed users."
    )


async def handle_broadcast_text(update, context, text, is_owner):
    if context.user_data.get("mode") != "awaiting_broadcast":
        return False

    if not is_owner(update.effective_user.id):
        return True

    settings = _load_settings()
    users = _extract_allowed_users(settings)

    ok = 0
    fail = 0

    for uid in users.keys():
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 Сообщение от owner:\n\n{text}"
            )
            ok += 1
        except Exception:
            fail += 1

    context.user_data.pop("mode", None)

    await update.message.reply_text(
        f"✅ Broadcast готов.\n\nОтправлено: {ok}\nНе доставлено: {fail}"
    )

    return True
