import logging
import json
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# Конфиг
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = -3794802790

TOPICS = ["CowGirl", "Student", "Meme", "Telegram", "X", "Threads"]

COUNTER_FILE = "counter.json"


def load_counter():
    """Загружает счетчик постов"""
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            for topic in TOPICS:
                if topic not in data:
                    data[topic] = 0

            return data

        except json.JSONDecodeError:
            logger.warning("counter.json поврежден. Создаю новый счетчик.")
            return {topic: 0 for topic in TOPICS}

        except Exception as e:
            logger.error(f"Ошибка при чтении counter.json: {e}")
            return {topic: 0 for topic in TOPICS}

    return {topic: 0 for topic in TOPICS}


def save_counter(counter):
    """Сохраняет счетчик постов"""
    try:
        with open(COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump(counter, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка при сохранении counter.json: {e}")


def get_topic_id(name):
    """Возвращает ID топика по названию"""
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
    """Проверяет, есть ли ссылка в тексте"""
    return "http://" in text or "https://" in text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "Привет! Просто отправь мне ссылку и мысли одним сообщением.\n\n"
        "Пример:\n"
        "https://example.com идея для поста\n\n"
        "Или можешь использовать старый вариант:\n"
        "/save https://example.com идея для поста"
    )


async def save_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /save"""

    if not context.args:
        await update.message.reply_text(
            "Ошибка! Используй:\n\n"
            "/save [ссылка] [мысли]\n\n"
            "Пример:\n"
            "/save https://example.com идея для поста"
        )
        return

    text = " ".join(context.args).strip()

    await process_content(update, context, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений без /save"""

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    await process_content(update, context, text)


async def process_content(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Общая обработка контента"""

    if not has_link(text):
        await update.message.reply_text(
            "Отправь ссылку и мысли одним сообщением.\n\n"
            "Пример:\n"
            "https://example.com идея для поста"
        )
        return

    context.user_data["content"] = text

    keyboard = [
        [InlineKeyboardButton(topic, callback_data=f"t_{topic}")]
        for topic in TOPICS
    ]

    await update.message.reply_text(
        "Выбери топик:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def on_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора топика"""

    query = update.callback_query
    await query.answer()

    topic = query.data.replace("t_", "")

    if topic not in TOPICS:
        await query.edit_message_text("Ошибка: неизвестный топик.")
        return

    content = context.user_data.get("content")

    if not content:
        await query.edit_message_text(
            "Ошибка: контент не найден. Отправь ссылку заново."
        )
        return

    parts = content.split(maxsplit=1)

    url = parts[0]
    thought = parts[1] if len(parts) > 1 else "Без текста"

    counter = load_counter()

    counter[topic] += 1
    post_number = counter[topic]

    save_counter(counter)

    message_text = (
        f"📌 Post #{post_number}\n\n"
        f"📂 Topic: {topic}\n\n"
        f"💭 Мысли:\n{thought}\n\n"
        f"🔗 Ссылка:\n{url}\n\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    try:
        topic_id = get_topic_id(topic)

        if topic_id is not None:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=topic_id,
                text=message_text
            )
        else:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=message_text
            )

        await query.edit_message_text(
            f"✅ Сохранено в {topic}\n"
            f"📌 Post #{post_number}"
        )

        context.user_data.pop("content", None)

    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
        await query.edit_message_text(f"❌ Ошибка: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    logger.error(f"Update {update} caused error: {context.error}")


def main():
    """Запуск бота"""

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN не найден. Укажи его в переменных окружения."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("save", save_cmd))

    # Обычные сообщения без /save
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_handler(CallbackQueryHandler(on_topic, pattern="^t_"))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
