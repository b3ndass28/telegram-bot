import json
import time
import zipfile
from datetime import datetime
from pathlib import Path

from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import SETTINGS_FILE, DATABASE_FILE, REMINDERS_FILE, DOWNLOAD_DIR, BACKUP_SETTINGS_FILE


def backup_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 Создать бэкап", callback_data="backup_now")],
        [InlineKeyboardButton("♻️ Восстановить", callback_data="restore_start")],
        [InlineKeyboardButton("📦 Подключить backup-чат", callback_data="backup_connect_help")],
        [
            InlineKeyboardButton("🔁 Автобэкап ON", callback_data="autobackup_on"),
            InlineKeyboardButton("⏸ Автобэкап OFF", callback_data="autobackup_off"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ])


def _read_json(path, default):
    path = Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            pass
    return default


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_backup_zip():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DOWNLOAD_DIR / f"referens_backup_{ts}.zip"

    files = [
        ("settings.json", SETTINGS_FILE),
        ("database.json", DATABASE_FILE),
        ("reminders.json", REMINDERS_FILE),
        ("backup_settings.json", BACKUP_SETTINGS_FILE),
    ]

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, path in files:
            path = Path(path)
            if path.exists():
                z.write(path, arcname)
            else:
                z.writestr(arcname, "{}")

    return str(backup_path)


def restore_from_backup_zip(zip_path):
    targets = {
        "settings.json": SETTINGS_FILE,
        "database.json": DATABASE_FILE,
        "reminders.json": REMINDERS_FILE,
        "backup_settings.json": BACKUP_SETTINGS_FILE,
    }

    restored = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for item in z.namelist():
            name = Path(item).name
            if name not in targets:
                continue

            raw = z.read(item)
            json.loads(raw.decode("utf-8") or "{}")  # validate JSON
            Path(targets[name]).write_bytes(raw)
            restored.append(name)

    return restored


def load_backup_settings():
    data = _read_json(BACKUP_SETTINGS_FILE, {
        "enabled": False,
        "chat_id": None,
        "interval_hours": 3,
        "last_sent_ts": 0,
    })
    data.setdefault("enabled", False)
    data.setdefault("chat_id", None)
    data.setdefault("interval_hours", 3)
    data.setdefault("last_sent_ts", 0)
    return data


def save_backup_settings(data):
    _write_json(BACKUP_SETTINGS_FILE, data)


async def backup_cmd(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if not await require_owner(update, context):
        return
    path = create_backup_zip()
    with open(path, "rb") as f:
        await update.message.reply_document(document=InputFile(f, filename=Path(path).name), caption="💾 Бэкап готов.")


async def restore_cmd(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if not await require_owner(update, context):
        return
    context.user_data["mode"] = "awaiting_restore_zip"
    await update.message.reply_text("♻️ Восстановление\n\nОтправь backup .zip файлом. Он восстановит settings/database/reminders.")


async def connectbackup_cmd(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if not await require_owner(update, context):
        return

    settings = load_backup_settings()
    settings["chat_id"] = update.effective_chat.id
    save_backup_settings(settings)

    await update.message.reply_text(
        f"✅ Backup-чат подключён.\n\nChat ID: `{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def autobackup_on_cmd(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if not await require_owner(update, context):
        return
    settings = load_backup_settings()
    settings["enabled"] = True
    save_backup_settings(settings)
    await update.message.reply_text("✅ Автобэкап включён.")


async def autobackup_off_cmd(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if not await require_owner(update, context):
        return
    settings = load_backup_settings()
    settings["enabled"] = False
    save_backup_settings(settings)
    await update.message.reply_text("⏸ Автобэкап выключен.")


async def handle_restore_document(update, context: ContextTypes.DEFAULT_TYPE, require_owner):
    if context.user_data.get("mode") != "awaiting_restore_zip":
        return False

    if not await require_owner(update, context):
        return True

    document = update.message.document
    if not document or not document.file_name.endswith(".zip"):
        await update.message.reply_text("Отправь именно .zip backup файл.")
        return True

    file = await document.get_file()
    path = DOWNLOAD_DIR / f"restore_{int(time.time())}.zip"
    await file.download_to_drive(str(path))

    try:
        restored = restore_from_backup_zip(path)
        context.user_data.pop("mode", None)
        await update.message.reply_text("✅ Restore готов.\n\nВосстановлено:\n" + "\n".join(restored))
    except Exception as e:
        await update.message.reply_text(f"❌ Restore error: {e}")

    return True


async def autobackup_job(context: ContextTypes.DEFAULT_TYPE):
    settings = load_backup_settings()
    if not settings.get("enabled") or not settings.get("chat_id"):
        return

    now = time.time()
    interval_seconds = int(settings.get("interval_hours", 3)) * 3600
    if now - float(settings.get("last_sent_ts", 0)) < interval_seconds:
        return

    path = create_backup_zip()
    with open(path, "rb") as f:
        await context.bot.send_document(
            chat_id=int(settings["chat_id"]),
            document=InputFile(f, filename=Path(path).name),
            caption="💾 Auto backup",
        )

    settings["last_sent_ts"] = now
    save_backup_settings(settings)


async def backup_callback(update, context: ContextTypes.DEFAULT_TYPE, require_owner, safe_edit_message):
    query = update.callback_query
    await query.answer()

    if not await require_owner(update, context):
        return

    data = query.data

    if data == "backup_menu":
        settings = load_backup_settings()
        await safe_edit_message(
            query,
            f"💾 Бэкап\n\nАвтобэкап: {'ON' if settings.get('enabled') else 'OFF'}\nBackup-чат: {settings.get('chat_id')}",
            reply_markup=backup_keyboard(),
        )
        return

    if data == "backup_now":
        path = create_backup_zip()
        with open(path, "rb") as f:
            await query.message.reply_document(document=InputFile(f, filename=Path(path).name), caption="💾 Бэкап готов.")
        return

    if data == "restore_start":
        context.user_data["mode"] = "awaiting_restore_zip"
        await safe_edit_message(query, "♻️ Восстановление\n\nОтправь backup .zip файлом.")
        return

    if data == "backup_connect_help":
        await safe_edit_message(
            query,
            "📦 Подключить backup-чат\n\nСоздай приватный канал/чат для бэкапов, добавь туда бота админом и напиши там:\n\n/connectbackup",
            reply_markup=backup_keyboard(),
        )
        return

    if data == "autobackup_on":
        settings = load_backup_settings()
        settings["enabled"] = True
        save_backup_settings(settings)
        await safe_edit_message(query, "✅ Автобэкап включён.", reply_markup=backup_keyboard())
        return

    if data == "autobackup_off":
        settings = load_backup_settings()
        settings["enabled"] = False
        save_backup_settings(settings)
        await safe_edit_message(query, "⏸ Автобэкап выключен.", reply_markup=backup_keyboard())
        return
