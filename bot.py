import logging
import json
import os
import re
import uuid
import asyncio
import threading
from pathlib import Path

import yt_dlp
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# =========================
# WEB SERVER FOR RENDER
# =========================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Bot is running!"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ВАЖНО:
# Это ID твоей супергруппы для Bot API.
# Из ссылки https://t.me/c/3794802790/... получается -1003794802790
CHAT_ID = -1003794802790

TOPICS = ["CowGirl", "Student", "Meme", "Telegram", "X", "Threads"]

COUNTER_FILE = "counter.json"
PENDING_FILE = "pending.json"
DOWNLOAD_DIR = "downloads"

Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


# =========================
# FILE HELPERS
# =========================

def load_counter():
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            for topic in TOPICS:
                if topic not in data:
                    data[topic] = 0

            return data

        except Exception as e:
            logger.error(f"Ошибка чтения counter.json: {e}")
            return {topic: 0 for topic in TOPICS}

    return {topic: 0 for topic in TOPICS}


def save_counter(counter):
    try:
        with open(COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump(counter, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения counter.json: {e}")


def load_pending():
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения pending.json: {e}")
            return {}

    return {}


def save_pending(data):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения pending.json: {e}")


def set_pending_content(user_id, content):
    data = load_pending()
    data[str(user_id)] = content
    save_pending(data)


def get_pending_content(user_id):
    data = load_pending()
    return data.get(str(user_id))


def clear_pending_content(user_id):
    data = load_pending()
    data.pop(str(user_id), None)
    save_pending(data)


# =========================
# TELEGRAM HELPERS
# =========================

def get_topic_id(name):
    mapping = {
        "CowGirl": 2,
        "Student": 6,
        "Meme": 7,
        "Telegram": 4,
        "X": 8,
        "Threads": 9
    }

    return mapping.get(name)


def has_link(text: str) -> bool:
    return "http://" in text or "https://" in text


def extract_url_and_thought(text: str):
    url_match = re.search(r"https?://\S+", text)

    if not url_match:
        return None, text.strip()

    url = url_match.group(0).strip()
    thought = text.replace(url, "", 1).strip()

    if not thought:
        thought = "Без текста"

    return url, thought


def build_topic_keyboard():
    buttons_per_row = 3
    keyboard = []

    for i in range(0, len(TOPICS), buttons_per_row):
        row = []

        for topic in TOPICS[i:i + buttons_per_row]:
            row.append(
                InlineKeyboardButton(
                    topic,
                    callback_data=f"t_{topic}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    ])

    return InlineKeyboardMarkup(keyboard)


# =========================
# VIDEO DOWNLOAD
# =========================

def download_video_sync(url: str):
    video_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 48 * 1024 * 1024,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    if not os.path.exists(downloaded_path):
        possible_files = list(Path(DOWNLOAD_DIR).glob(f"{video_id}.*"))

        if possible_files:
            downloaded_path = str(possible_files[0])
        else:
            raise FileNotFoundError("Видео не было скачано.")

    return downloaded_path


async def download_video(url: str):
    return await asyncio.to_thread(download_video_sync, url)


# =========================
# BOT HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Просто отправь мне ссылку и мысли одним сообщением.\n\n"
        "Пример:\n"
        "https://www.tiktok.com/... идея для поста\n\n"
        "После этого выбери топик, и я сохраню пост."
    )


async def save_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Ошибка. Используй так:\n\n"
            "/save https://example.com твои мысли"
        )
        return

    text = " ".join(context.args).strip()
    await process_content(update, context, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    await process_content(update, context, text)


async def process_content(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not has_link(text):
        await update.message.reply_text(
            "Отправь ссылку и мысли одним сообщением.\n\n"
            "Пример:\n"
            "https://www.instagram.com/reel/... идея для поста"
        )
        return

    user_id = update.effective_user.id

    context.user_data["content"] = text
    set_pending_content(user_id, text)

    await update.message.reply_text(
        "Куда сохранить этот пост?",
        reply_markup=build_topic_keyboard()
    )


async def on_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "cancel":
        context.user_data.pop("content", None)
        clear_pending_content(user_id)

        await query.edit_message_text(
            "❌ Отменено.\n\n"
            "Можешь отправить новую ссылку."
        )
        return

    topic = query.data.replace("t_", "")

    if topic not in TOPICS:
        await query.edit_message_text("Ошибка: неизвестный топик.")
        return

    content = context.user_data.get("content") or get_pending_content(user_id)

    if not content:
        await query.edit_message_text(
            "Ошибка: контент не найден. Отправь ссылку заново."
        )
        return

    url, thought = extract_url_and_thought(content)

    if not url:
        await query.edit_message_text("Ошибка: ссылка не найдена.")
        return

    counter = load_counter()
    counter[topic] += 1
    post_number = counter[topic]
    save_counter(counter)

    caption_text = (
        f"📌 Post #{post_number}\n\n"
        f"🔗 Link:\n{url}\n\n"
        f"💭 Notes:\n{thought}"
    )

    topic_id = get_topic_id(topic)

    await query.edit_message_text(
        f"⏳ Скачиваю видео...\n\n"
        f"Топик: {topic}\n"
        f"Post #{post_number}"
    )

    video_path = None

    try:
        video_path = await download_video(url)

        with open(video_path, "rb") as video_file:
            if topic_id is not None:
                await context.bot.send_video(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    video=video_file,
                    caption=caption_text,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )
            else:
                await context.bot.send_video(
                    chat_id=CHAT_ID,
                    video=video_file,
                    caption=caption_text,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

        await query.edit_message_text(
            f"✅ Видео сохранено\n\n"
            f"📌 Post #{post_number}\n"
            f"📂 {topic}"
        )

        context.user_data.pop("content", None)
        clear_pending_content(user_id)

    except Exception as e:
        logger.error(f"Ошибка скачивания/отправки видео: {e}")

        fallback_text = (
            f"📌 Post #{post_number}\n\n"
            f"🔗 Link:\n{url}\n\n"
            f"💭 Notes:\n{thought}\n\n"
            f"⚠️ Видео не удалось скачать автоматически."
        )

        try:
            if topic_id is not None:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    text=fallback_text
                )
            else:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=fallback_text
                )

            await query.edit_message_text(
                f"⚠️ Видео не скачалось, но пост сохранен текстом.\n\n"
                f"📌 Post #{post_number}\n"
                f"📂 {topic}"
            )

            context.user_data.pop("content", None)
            clear_pending_content(user_id)

        except Exception as send_error:
            logger.error(f"Ошибка fallback-отправки: {send_error}")
            await query.edit_message_text(f"❌ Ошибка: {send_error}")

    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass


async def chat_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    thread_id = update.message.message_thread_id

    await update.message.reply_text(
        f"Chat ID: {chat.id}\n"
        f"Chat type: {chat.type}\n"
        f"Thread ID: {thread_id}"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Добавь BOT_TOKEN в Environment Variables на Render.")

    # Для Render Web Service
    threading.Thread(target=run_web_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("save", save_cmd))
    app.add_handler(CommandHandler("id", chat_id_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_handler(CallbackQueryHandler(on_topic, pattern="^(t_|cancel)"))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
