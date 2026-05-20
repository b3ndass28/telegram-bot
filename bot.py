import asyncio
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputFile
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from config import (
    BOT_TOKEN,
    CHAT_ID,
    TOPICS_IMAGE,
    INFO_IMAGE,
    EXPORT_IMAGE,
    COOKIES_FILE,
    DOWNLOAD_DIR,
    TOPICS_FILE,
    DATABASE_FILE,
    REMINDERS_FILE,
    PRIORITIES,
    STATUSES
)

from helpers import (
    load_topics,
    save_topics,
    get_topic_names,
    get_topic_id,
    get_topic_icon,
    guess_topic_icon,
    topics_text,
    add_database_item,
    update_database_item,
    load_database,
    load_reminders,
    add_reminder,
    reminders_job,
    set_pending_content,
    get_pending_content,
    clear_pending_content,
    has_link,
    extract_url_and_thought,
    clean_url,
    normalize_instagram_url,
    extract_instagram_username,
    extract_profile_username,
    detect_platform,
    is_instagram_profile,
    is_tiktok_profile,
    is_x_profile,
    is_threads_profile,
    is_social_profile,
    safe_file_exists,
    build_video_caption,
    build_profile_caption,
    build_reminder_text,
    remove_active_reminders_for_item,
    current_timestamp,
    send_photo_or_text_message,
    edit_or_send_photo,
    safe_edit_message,
    download_video,
    make_profile_screenshot,
    create_export_json,
    create_export_csv,
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
# INFO TEXTS
# =========================

INFO_SHORT_TEXT = (
    "ℹ️ Referens Bot\n\n"
    "Главная функция бота — сохранять контент-референсы уже вместе с медиа, "
    "твоими заметками, приоритетом, статусом и напоминаниями.\n\n"
    "Отправь ссылку + свою мысль → выбери топик → выбери приоритет → бот сохранит референс в нужный раздел."
)

INFO_LONG_TEXT = (
    "Что умеет бот:\n\n"
    "🎬 Сохранять видео-референсы\n"
    "Бот может скачать поддерживаемое видео из Instagram, TikTok, YouTube и других источников "
    "и отправить его в выбранный топик.\n\n"
    "💭 Сохранять твои заметки\n"
    "Вместе с видео сохраняются твои мысли: что понравилось, как адаптировать идею, какой хук, стиль, монтаж или сценарий повторить.\n\n"
    "📸 Делать скрин Instagram-аккаунтов\n"
    "Если отправить ссылку на Instagram, TikTok, X или Threads профиль, бот делает скрин аккаунта и сохраняет его как референс без priority/status/reminder.\n\n"
    "📂 Раскладывать всё по топикам\n"
    "Топики можно создавать, переименовывать и удалять прямо через бота.\n\n"
    "⚡ Приоритет\n"
    "🔥 High — использовать быстрее\n"
    "⭐ Normal — обычная хорошая идея\n"
    "🧊 Later — идея на потом\n\n"
    "📌 Статус\n"
    "🆕 New — новая идея\n"
    "🟡 In Progress — в работе\n"
    "✅ Done — сделано\n"
    "❌ Not Suitable — не подходит\n\n"
    "🔔 Напоминания\n"
    "Можно поставить reminder от 1 до 15 дней или тест на 1 минуту.\n\n"
    "🧵 Threads\n"
    "Threads-посты сейчас сохраняются как ссылка + notes, без попытки скачать видео. Threads-профили можно сохранять скриншотом.\n\n"
    "📤 Export\n"
    "Базу идей можно выгрузить в JSON или CSV.\n\n"
    "Пример:\n"
    "https://www.instagram.com/reel/... хороший хук, можно адаптировать под cowgirl-видео"
)


# =========================
# KEYBOARDS
# =========================

def build_reply_panel():
    keyboard = [
        [
            KeyboardButton("📂 Topics"),
            KeyboardButton("ℹ️ Info"),
            KeyboardButton("📤 Export")
        ],
        [
            KeyboardButton("✅ Check")
        ]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )


def build_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📂 Topics", callback_data="menu_topics"),
            InlineKeyboardButton("ℹ️ Info", callback_data="menu_info")
        ],
        [
            InlineKeyboardButton("📤 Export", callback_data="menu_export"),
            InlineKeyboardButton("✅ Check", callback_data="menu_check")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="menu_close")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_topics_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Создать новый", callback_data="topics_create")],
        [InlineKeyboardButton("✏️ Изменить текущий", callback_data="topics_rename")],
        [InlineKeyboardButton("🗑️ Удалить", callback_data="topics_delete")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"),
            InlineKeyboardButton("❌ Закрыть", callback_data="menu_close")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_export_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📄 JSON", callback_data="export_json"),
            InlineKeyboardButton("📊 CSV", callback_data="export_csv")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"),
            InlineKeyboardButton("❌ Закрыть", callback_data="menu_close")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_topic_keyboard():
    topics = load_topics()
    buttons_per_row = 3
    keyboard = []

    topic_names = list(topics.keys())

    for i in range(0, len(topic_names), buttons_per_row):
        row = []

        for topic in topic_names[i:i + buttons_per_row]:
            icon = topics[topic].get("icon", "📂")
            row.append(
                InlineKeyboardButton(
                    f"{icon} {topic}",
                    callback_data=f"t_{topic}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_save")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_initial_priority_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔥 High", callback_data="save_priority_high"),
            InlineKeyboardButton("⭐ Normal", callback_data="save_priority_normal"),
            InlineKeyboardButton("🧊 Later", callback_data="save_priority_later")
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_save")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_post_action_keyboard(item_id):
    keyboard = [
        [
            InlineKeyboardButton("⚡ Priority", callback_data=f"post_priority_menu:{item_id}"),
            InlineKeyboardButton("📌 Status", callback_data=f"post_status_menu:{item_id}")
        ],
        [
            InlineKeyboardButton("🔔 Reminder", callback_data=f"post_reminder_menu:{item_id}")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_priority_manage_keyboard(item_id):
    keyboard = [
        [
            InlineKeyboardButton("🔥 High", callback_data=f"post_priority_set:high:{item_id}"),
            InlineKeyboardButton("⭐ Normal", callback_data=f"post_priority_set:normal:{item_id}"),
            InlineKeyboardButton("🧊 Later", callback_data=f"post_priority_set:later:{item_id}")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"post_back:{item_id}")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_status_manage_keyboard(item_id):
    keyboard = [
        [
            InlineKeyboardButton("🟡 В работе", callback_data=f"post_status_set:progress:{item_id}"),
            InlineKeyboardButton("✅ Сделано", callback_data=f"post_status_set:done:{item_id}")
        ],
        [
            InlineKeyboardButton("❌ Не подходит", callback_data=f"post_status_set:bad:{item_id}")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"post_back:{item_id}")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_reminder_manage_keyboard(item_id):
    keyboard = []

    keyboard.append([
        InlineKeyboardButton("🧪 1 min test", callback_data=f"post_reminder_set:test:{item_id}")
    ])

    for start in range(1, 16, 3):
        row = []
        for day in range(start, min(start + 3, 16)):
            row.append(
                InlineKeyboardButton(
                    f"{day}d",
                    callback_data=f"post_reminder_set:{day}d:{item_id}"
                )
            )
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("🗑 Remove reminder", callback_data=f"post_reminder_remove:{item_id}")
    ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"post_back:{item_id}")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_topic_select_keyboard(action):
    topics = load_topics()
    keyboard = []

    for name, data in topics.items():
        icon = data.get("icon", "📂")
        keyboard.append([
            InlineKeyboardButton(
                f"{icon} {name}",
                callback_data=f"{action}:{name}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="menu_topics"),
        InlineKeyboardButton("❌ Отмена", callback_data="menu_close")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_delete_confirm_keyboard(topic_name):
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{topic_name}")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="topics_delete"),
            InlineKeyboardButton("❌ Отмена", callback_data="menu_close")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_back_cancel_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="menu_topics"),
            InlineKeyboardButton("❌ Отмена", callback_data="menu_close")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# FALLBACK HELPERS
# =========================

def should_screenshot_post_fallback(platform: str) -> bool:
    return platform in {
        "X Post",
        "Instagram Post",
    }


def is_threads_download_disabled(platform: str) -> bool:
    return platform in {
        "Threads Post",
        "Threads",
    }


# =========================
# POST UPDATE
# =========================

async def update_post_message(query, item):
    new_caption = build_video_caption(
        item.get("platform", "Unknown"),
        item.get("url", ""),
        item.get("notes", ""),
        item.get("priority_label", ""),
        item.get("status_label", ""),
        item.get("reminder_label")
    )

    try:
        await query.edit_message_caption(
            caption=new_caption,
            reply_markup=build_post_action_keyboard(item.get("id"))
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=new_caption,
                reply_markup=build_post_action_keyboard(item.get("id"))
            )
        except Exception as e:
            logger.error(f"Не удалось обновить пост: {type(e).__name__}: {repr(e)}")



def log_background_task_result(task):
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Background save task was cancelled.")
    except Exception as e:
        logger.error(f"Background save task crashed: {type(e).__name__}: {repr(e)}")


async def start_save_background_task(query, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts long save/download/screenshot work in the background.
    This keeps the bot responsive, so new links can immediately get the "please wait" message.
    """
    user_id = query.from_user.id

    if context.application.bot_data.get(f"processing_{user_id}"):
        await query.message.reply_text(
            "⏳ Пожалуйста, подожди. Сейчас бот уже обрабатывает предыдущий референс."
        )
        return

    context.application.bot_data[f"processing_{user_id}"] = True
    task = asyncio.create_task(save_selected_content(query, context))
    task.add_done_callback(log_background_task_result)


# =========================
# COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Отправь мне ссылку и мысли одним сообщением.\n\n"
        "Панель открыта снизу ✅",
        reply_markup=build_reply_panel()
    )


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Панель открыта ✅",
        reply_markup=build_reply_panel()
    )


async def hide_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Панель скрыта ✅",
        reply_markup=ReplyKeyboardRemove()
    )


async def test_reminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = {
        "platform": "Instagram Reels",
        "priority_label": "🔥 High",
        "status_label": "🟡 In Progress",
        "url": "https://www.instagram.com/reel/example/",
        "notes": "Тестовое напоминание. Так будет выглядеть reminder, когда он придёт."
    }

    await update.message.reply_text(build_reminder_text(item))


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Главное меню\n\nЧто хочешь сделать?",
        reply_markup=build_main_menu_keyboard()
    )


async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_photo_or_text_message(
        update.message,
        TOPICS_IMAGE,
        f"{topics_text()}\n\nЧто хочешь сделать?",
        reply_markup=build_topics_menu_keyboard()
    )


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if safe_file_exists(INFO_IMAGE):
        with open(INFO_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=INFO_SHORT_TEXT,
                reply_markup=build_main_menu_keyboard()
            )
        await update.message.reply_text(INFO_LONG_TEXT)
    else:
        await update.message.reply_text(
            f"{INFO_SHORT_TEXT}\n\n{INFO_LONG_TEXT}",
            reply_markup=build_main_menu_keyboard()
        )


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_photo_or_text_message(
        update.message,
        EXPORT_IMAGE,
        "📤 Export\n\nВыбери формат экспорта базы:",
        reply_markup=build_export_keyboard()
    )


async def add_topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 1:
        name = context.args[0].strip()

        try:
            created = await context.bot.create_forum_topic(
                chat_id=CHAT_ID,
                name=name
            )

            topic_id = created.message_thread_id
            topics = load_topics()

            if name in topics:
                await update.message.reply_text(f"Топик {name} уже есть в боте.")
                return

            topics[name] = {
                "id": topic_id,
                "icon": guess_topic_icon(name)
            }

            save_topics(topics)

            await update.message.reply_text(
                f"✅ Telegram-топик создан и добавлен в бота:\n\n"
                f"{topics[name]['icon']} {name} — ID: {topic_id}"
            )
            return

        except Exception as e:
            await update.message.reply_text(
                f"❌ Не удалось создать Telegram-топик.\n\n"
                f"Проверь, что бот админ и имеет право Manage Topics.\n\n"
                f"Ошибка: {e}"
            )
            return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Используй так:\n\n"
            "/addtopic Название\n"
            "чтобы бот сам создал Telegram-топик\n\n"
            "или:\n"
            "/addtopic Название ID\n"
            "если тема уже существует"
        )
        return

    name = context.args[0].strip()
    topic_id_raw = context.args[1].strip()

    try:
        topic_id = int(topic_id_raw)
    except ValueError:
        await update.message.reply_text("ID топика должен быть числом.")
        return

    topics = load_topics()

    if name in topics:
        await update.message.reply_text(f"Топик {name} уже существует.")
        return

    topics[name] = {
        "id": topic_id,
        "icon": guess_topic_icon(name)
    }

    save_topics(topics)

    await update.message.reply_text(
        f"✅ Топик добавлен вручную:\n\n"
        f"{topics[name]['icon']} {name} — ID: {topic_id}"
    )


async def rename_topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Используй так:\n\n"
            "/renametopic СтароеНазвание НовоеНазвание\n\n"
            "Пример:\n"
            "/renametopic CowGirl Cowgirl"
        )
        return

    old_name = context.args[0].strip()
    new_name = context.args[1].strip()

    topics = load_topics()

    if old_name not in topics:
        await update.message.reply_text(f"Топик {old_name} не найден.")
        return

    if new_name in topics:
        await update.message.reply_text(f"Топик {new_name} уже существует.")
        return

    topic_id = topics[old_name]["id"]

    try:
        await context.bot.edit_forum_topic(
            chat_id=CHAT_ID,
            message_thread_id=topic_id,
            name=new_name
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось переименовать Telegram-топик.\n\n"
            f"Проверь права бота на управление темами.\n\n"
            f"Ошибка: {e}"
        )
        return

    topics[new_name] = topics.pop(old_name)
    topics[new_name]["icon"] = guess_topic_icon(new_name)

    save_topics(topics)

    await update.message.reply_text(
        f"✅ Топик переименован:\n\n"
        f"{old_name} → {topics[new_name]['icon']} {new_name}"
    )


async def delete_topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Удаление через команду отключено для безопасности.\n\n"
        "Используй меню:\n"
        "📂 Topics → 🗑️ Удалить → выбери топик → подтверди удаление."
    )


# =========================
# MENU CALLBACK
# =========================

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "menu_main":
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)

        await safe_edit_message(
            query,
            "⚙️ Главное меню\n\nЧто хочешь сделать?",
            reply_markup=build_main_menu_keyboard()
        )
        return

    if data == "menu_close":
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("content", None)
        clear_pending_content(user_id)

        await safe_edit_message(query, "✅ Закрыто.")
        return

    if data == "menu_topics":
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)

        await edit_or_send_photo(
            query,
            TOPICS_IMAGE,
            f"{topics_text()}\n\nЧто хочешь сделать?",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    if data == "menu_info":
        try:
            await query.message.delete()
        except Exception:
            pass

        if safe_file_exists(INFO_IMAGE):
            with open(INFO_IMAGE, "rb") as photo:
                await query.message.chat.send_photo(
                    photo=photo,
                    caption=INFO_SHORT_TEXT,
                    reply_markup=build_main_menu_keyboard()
                )
            await query.message.chat.send_message(INFO_LONG_TEXT)
        else:
            await query.message.chat.send_message(
                f"{INFO_SHORT_TEXT}\n\n{INFO_LONG_TEXT}",
                reply_markup=build_main_menu_keyboard()
            )
        return

    if data == "menu_export":
        await edit_or_send_photo(
            query,
            EXPORT_IMAGE,
            "📤 Export\n\nВыбери формат экспорта базы:",
            reply_markup=build_export_keyboard()
        )
        return

    if data == "menu_check":
        cookies_exists = Path(COOKIES_FILE).exists()
        topics = load_topics()
        database = load_database()
        reminders = load_reminders()

        await safe_edit_message(
            query,
            f"✅ Проверка бота\n\n"
            f"Cookies file: {'✅ найден' if cookies_exists else '❌ не найден'}\n"
            f"Topics count: {len(topics)}\n"
            f"Database items: {len(database)}\n"
            f"Reminders count: {len(reminders)}\n"
            f"Docker mode: ✅ Playwright enabled",
            reply_markup=build_main_menu_keyboard()
        )
        return

    if data == "topics_create":
        context.user_data["mode"] = "awaiting_new_topic"

        text = (
            "➕ Создание нового топика\n\n"
            "Отправь название нового топика одним сообщением.\n\n"
            "Пример:\n"
            "Cars\n\n"
            "Бот сам создаст Telegram-топик в группе и добавит его в список.\n\n"
            "Важно: у бота должны быть права Manage Topics."
        )

        await safe_edit_message(
            query,
            text,
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if data == "topics_rename":
        context.user_data["mode"] = "select_rename_topic"

        await safe_edit_message(
            query,
            "✏️ Выбери топик, который хочешь переименовать:",
            reply_markup=build_topic_select_keyboard("rename_select")
        )
        return

    if data == "topics_delete":
        context.user_data["mode"] = "select_delete_topic"

        await safe_edit_message(
            query,
            "🗑️ Выбери топик, который хочешь удалить:",
            reply_markup=build_topic_select_keyboard("delete_select")
        )
        return

    if data.startswith("rename_select:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await safe_edit_message(
                query,
                "Топик не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        context.user_data["mode"] = "awaiting_rename_topic"
        context.user_data["selected_topic"] = topic_name

        icon = topics[topic_name].get("icon", "📂")
        topic_id = topics[topic_name].get("id")

        await safe_edit_message(
            query,
            f"✏️ Переименование топика\n\n"
            f"Текущий топик:\n"
            f"{icon} {topic_name} — ID: {topic_id}\n\n"
            f"Отправь новое название одним сообщением.\n\n"
            f"Бот переименует и Telegram-топик, и кнопку в боте.",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if data.startswith("delete_select:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await safe_edit_message(
                query,
                "Топик не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        icon = topics[topic_name].get("icon", "📂")
        topic_id = topics[topic_name].get("id")

        await safe_edit_message(
            query,
            f"⚠️ Точно удалить топик?\n\n"
            f"{icon} {topic_name} — ID: {topic_id}\n\n"
            f"Это удалит Telegram-топик из группы и уберёт его из бота.\n\n"
            f"Действие лучше не делать случайно.",
            reply_markup=build_delete_confirm_keyboard(topic_name)
        )
        return

    if data.startswith("confirm_delete:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await safe_edit_message(
                query,
                "Топик уже не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        topic_id = topics[topic_name]["id"]

        try:
            await context.bot.delete_forum_topic(
                chat_id=CHAT_ID,
                message_thread_id=topic_id
            )
        except Exception as e:
            await safe_edit_message(
                query,
                f"❌ Не удалось удалить Telegram-топик.\n\n"
                f"Проверь права бота на управление темами.\n\n"
                f"Ошибка: {e}",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        removed = topics.pop(topic_name)
        save_topics(topics)

        await safe_edit_message(
            query,
            f"🗑️ Топик удалён:\n\n"
            f"{topic_name} — ID: {removed.get('id')}\n\n"
            f"{topics_text()}",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    if data == "export_json":
        try:
            path = create_export_json()

            with open(path, "rb") as f:
                await query.message.reply_document(
                    document=InputFile(f, filename="referens_database.json"),
                    caption="📄 JSON export готов."
                )

        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка экспорта JSON: {e}")

        return

    if data == "export_csv":
        try:
            path = create_export_csv()

            with open(path, "rb") as f:
                await query.message.reply_document(
                    document=InputFile(f, filename="referens_database.csv"),
                    caption="📊 CSV export готов."
                )

        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка экспорта CSV: {e}")

        return


# =========================
# SAVE / POST ACTION CALLBACKS
# =========================

async def save_priority_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "cancel_save":
        context.user_data.pop("content", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("selected_topic_icon", None)
        clear_pending_content(user_id)

        try:
            await query.edit_message_caption("❌ Отменено.\n\nМожешь отправить новую ссылку.")
        except Exception:
            await query.edit_message_text("❌ Отменено.\n\nМожешь отправить новую ссылку.")
        return

    priority_key = data.replace("save_priority_", "")

    if priority_key not in PRIORITIES:
        await query.message.reply_text("Ошибка: неизвестный priority.")
        return

    context.user_data["selected_priority"] = priority_key

    await start_save_background_task(query, context)


async def post_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("post_priority_menu:"):
        item_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=build_priority_manage_keyboard(item_id))
        return

    if data.startswith("post_status_menu:"):
        item_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=build_status_manage_keyboard(item_id))
        return

    if data.startswith("post_reminder_menu:"):
        item_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=build_reminder_manage_keyboard(item_id))
        return

    if data.startswith("post_back:"):
        item_id = data.split(":", 1)[1]
        await query.edit_message_reply_markup(reply_markup=build_post_action_keyboard(item_id))
        return

    if data.startswith("post_priority_set:"):
        _, priority_key, item_id = data.split(":", 2)

        priority = PRIORITIES.get(priority_key)

        if not priority:
            await query.answer("Unknown priority", show_alert=True)
            return

        item = update_database_item(item_id, {
            "priority": priority_key,
            "priority_label": priority["label"]
        })

        if not item:
            await query.answer("Item not found", show_alert=True)
            return

        await update_post_message(query, item)
        return

    if data.startswith("post_status_set:"):
        _, status_key, item_id = data.split(":", 2)

        status_label = STATUSES.get(status_key)

        if not status_label:
            await query.answer("Unknown status", show_alert=True)
            return

        item = update_database_item(item_id, {
            "status": status_key,
            "status_label": status_label
        })

        if not item:
            await query.answer("Item not found", show_alert=True)
            return

        await update_post_message(query, item)
        return

    if data.startswith("post_reminder_remove:"):
        item_id = data.split(":", 1)[1]

        remove_active_reminders_for_item(item_id)

        item = update_database_item(item_id, {
            "reminder": None,
            "reminder_label": None,
            "reminder_due_ts": None
        })

        if not item:
            await query.answer("Item not found", show_alert=True)
            return

        await update_post_message(query, item)
        await query.answer("Reminder removed", show_alert=False)
        return

    if data.startswith("post_reminder_set:"):
        _, reminder_key, item_id = data.split(":", 2)

        if reminder_key == "test":
            seconds = 60
            label = "🧪 Test — 1 min"
        elif reminder_key.endswith("d") and reminder_key[:-1].isdigit():
            days = int(reminder_key[:-1])
            if days < 1 or days > 15:
                await query.answer("Reminder must be from 1 to 15 days", show_alert=True)
                return
            seconds = days * 24 * 60 * 60
            label = f"🔔 {days} day" if days == 1 else f"🔔 {days} days"
        else:
            await query.answer("Unknown reminder", show_alert=True)
            return

        due_ts = time.time() + seconds
        add_reminder(item_id, query.from_user.id, due_ts, label)

        item = update_database_item(item_id, {
            "reminder": reminder_key,
            "reminder_label": label,
            "reminder_due_ts": due_ts
        })

        if not item:
            await query.answer("Item not found", show_alert=True)
            return

        await update_post_message(query, item)
        await query.answer(f"Reminder set: {label}", show_alert=False)
        return


# =========================
# MESSAGE HANDLERS
# =========================

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
    mode = context.user_data.get("mode")
    user_id = update.effective_user.id

    if context.application.bot_data.get(f"processing_{user_id}") and has_link(text):
        old_queue = context.application.bot_data.get(f"queued_{user_id}")

        if old_queue:
            try:
                await context.bot.delete_message(
                    chat_id=old_queue.get("chat_id"),
                    message_id=old_queue.get("message_id")
                )
            except Exception:
                pass

        wait_message = await update.message.reply_text(
            "⏳ Пожалуйста, подожди. Сейчас бот уже обрабатывает предыдущий референс.\n\n"
            "Когда процесс закончится, я автоматически открою выбор топика для этой ссылки."
        )

        context.application.bot_data[f"queued_{user_id}"] = {
            "content": text,
            "chat_id": update.effective_chat.id,
            "message_id": wait_message.message_id
        }
        return

    if text == "📂 Topics":
        await topics_cmd(update, context)
        return

    if text == "ℹ️ Info":
        await info_cmd(update, context)
        return

    if text == "📤 Export":
        await export_cmd(update, context)
        return

    if text == "✅ Check":
        await check_cmd(update, context)
        return

    if mode == "awaiting_new_topic":
        await handle_new_topic_text(update, context, text)
        return

    if mode == "awaiting_rename_topic":
        await handle_rename_topic_text(update, context, text)
        return

    await process_content(update, context, text)


async def handle_new_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    name = text.strip()

    if not name:
        await update.message.reply_text(
            "Название не может быть пустым.\n\n"
            "Пример:\n"
            "Cars",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if len(name) > 128:
        await update.message.reply_text(
            "Название слишком длинное. Telegram-топик должен быть короче.",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    topics = load_topics()

    if name in topics:
        await update.message.reply_text(
            f"Топик {name} уже существует.",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    try:
        created = await context.bot.create_forum_topic(
            chat_id=CHAT_ID,
            name=name
        )

        topic_id = created.message_thread_id

    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось создать Telegram-топик.\n\n"
            f"Проверь, что бот админ и имеет право Manage Topics.\n\n"
            f"Ошибка: {e}",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    topics[name] = {
        "id": topic_id,
        "icon": guess_topic_icon(name)
    }

    save_topics(topics)

    context.user_data.pop("mode", None)

    await update.message.reply_text(
        f"✅ Telegram-топик создан и добавлен в бота:\n\n"
        f"{topics[name]['icon']} {name} — ID: {topic_id}\n\n"
        f"{topics_text()}",
        reply_markup=build_topics_menu_keyboard()
    )


async def handle_rename_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    old_name = context.user_data.get("selected_topic")
    new_name = text.strip()

    if not old_name:
        context.user_data.pop("mode", None)
        await update.message.reply_text(
            "Ошибка: топик не выбран.",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    if not new_name:
        await update.message.reply_text(
            "Новое название не может быть пустым.",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if len(new_name) > 128:
        await update.message.reply_text(
            "Название слишком длинное. Telegram-топик должен быть короче.",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    topics = load_topics()

    if old_name not in topics:
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)

        await update.message.reply_text(
            "Старый топик не найден.",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    if new_name in topics:
        await update.message.reply_text(
            f"Топик {new_name} уже существует. Отправь другое название.",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    topic_id = topics[old_name]["id"]

    try:
        await context.bot.edit_forum_topic(
            chat_id=CHAT_ID,
            message_thread_id=topic_id,
            name=new_name
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Не удалось переименовать Telegram-топик.\n\n"
            f"Проверь права бота на управление темами.\n\n"
            f"Ошибка: {e}",
            reply_markup=build_topics_menu_keyboard()
        )
        return

    topics[new_name] = topics.pop(old_name)
    topics[new_name]["icon"] = guess_topic_icon(new_name)

    save_topics(topics)

    context.user_data.pop("mode", None)
    context.user_data.pop("selected_topic", None)

    await update.message.reply_text(
        f"✅ Топик переименован:\n\n"
        f"{old_name} → {topics[new_name]['icon']} {new_name}\n\n"
        f"{topics_text()}",
        reply_markup=build_topics_menu_keyboard()
    )



async def ask_topic_prompt_for_content(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, text: str):
    """
    Sends the "choose topic" prompt for a link.
    Used both for normal messages and queued messages after a previous process finishes.
    """
    context.user_data["content"] = text
    set_pending_content(user_id, text)

    url, _ = extract_url_and_thought(text)

    if url and ("threads.com" in url.lower() or "threads.net" in url.lower()):
        from helpers import normalize_threads_url
        url = normalize_threads_url(url)

    if url and is_social_profile(url):
        platform = detect_platform(url)
        caption = f"📸 {platform}\n\n📌 Куда сохранить профиль?"
    else:
        caption = "📌 Куда сохранить?"

    if safe_file_exists(TOPICS_IMAGE):
        with open(TOPICS_IMAGE, "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=build_topic_keyboard()
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=build_topic_keyboard()
        )


async def process_content(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not has_link(text):
        return

    user_id = update.effective_user.id

    await ask_topic_prompt_for_content(
        context=context,
        chat_id=update.effective_chat.id,
        user_id=user_id,
        text=text
    )


async def on_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "cancel_save":
        context.user_data.pop("content", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("selected_topic_icon", None)
        clear_pending_content(user_id)

        try:
            await query.edit_message_caption("❌ Отменено.\n\nМожешь отправить новую ссылку.")
        except Exception:
            await query.edit_message_text("❌ Отменено.\n\nМожешь отправить новую ссылку.")
        return

    topic = query.data.replace("t_", "")

    if topic not in get_topic_names():
        try:
            await query.edit_message_caption("Ошибка: неизвестный топик.")
        except Exception:
            await query.edit_message_text("Ошибка: неизвестный топик.")
        return

    context.user_data["selected_topic"] = topic
    context.user_data["selected_topic_icon"] = get_topic_icon(topic)

    content = context.user_data.get("content") or get_pending_content(user_id)
    url, _ = extract_url_and_thought(content or "")

    if url and ("threads.com" in url.lower() or "threads.net" in url.lower()):
        from helpers import normalize_threads_url
        url = normalize_threads_url(url)

    if url and is_social_profile(url):
        await start_save_background_task(query, context)
        return

    topic_icon = get_topic_icon(topic)

    try:
        await query.edit_message_caption(
            caption=(
                f"{topic_icon} Topic: {topic}\n\n"
                f"⚡ Выбери priority:"
            ),
            reply_markup=build_initial_priority_keyboard()
        )
    except Exception:
        await query.edit_message_text(
            f"{topic_icon} Topic: {topic}\n\n"
            f"⚡ Выбери priority:",
            reply_markup=build_initial_priority_keyboard()
        )


async def save_selected_content(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id

    # This function runs in background. The processing flag is set before the task starts,
    # but we set it here too as a safety net.
    context.application.bot_data[f"processing_{user_id}"] = True

    content = context.user_data.get("content") or get_pending_content(user_id)
    topic = context.user_data.get("selected_topic")
    priority_key = context.user_data.get("selected_priority", "normal")

    if not content:
        await query.message.reply_text("Ошибка: контент не найден. Отправь ссылку заново.")
        return

    if not topic:
        await query.message.reply_text("Ошибка: топик не выбран. Отправь ссылку заново.")
        return

    url, thought = extract_url_and_thought(content)

    if not url:
        await query.message.reply_text("Ошибка: ссылка не найдена.")
        return

    if "instagram.com" in url.lower():
        url = normalize_instagram_url(url)
    elif "threads.com" in url.lower() or "threads.net" in url.lower():
        from helpers import normalize_threads_url
        url = normalize_threads_url(url)
    else:
        url = clean_url(url)

    platform = detect_platform(url)
    topic_id = get_topic_id(topic)
    topic_icon = get_topic_icon(topic)

    item_id = str(uuid.uuid4())
    media_path = None
    sent_message = None

    try:
        if is_social_profile(url):
            loading_caption = (
                f"📸 Делаю скриншот профиля...\n\n"
                f"{topic_icon} {topic}\n"
                f"🎬 {platform}"
            )

            try:
                await query.edit_message_caption(caption=loading_caption)
            except Exception:
                await query.edit_message_text(loading_caption)

            media_path = await make_profile_screenshot(url)

            caption_text = build_profile_caption(url, thought, platform)

            with open(media_path, "rb") as photo_file:
                sent_message = await context.bot.send_photo(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    photo=photo_file,
                    caption=caption_text,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

            success_caption = (
                f"✅ Скриншот профиля сохранён\n\n"
                f"{topic_icon} {topic}\n"
                f"🎬 {platform}"
            )

            try:
                await query.edit_message_caption(caption=success_caption)
            except Exception:
                await query.edit_message_text(success_caption)

            db_item = {
                "id": item_id,
                "created_at": current_timestamp(),
                "updated_at": current_timestamp(),
                "type": "profile_reference",
                "topic": topic,
                "topic_id": topic_id,
                "topic_icon": topic_icon,
                "platform": platform,
                "username": extract_profile_username(url, platform),
                "url": url,
                "notes": thought,
                "chat_id": CHAT_ID,
                "message_id": sent_message.message_id if sent_message else None
            }

            add_database_item(db_item)

        elif is_threads_download_disabled(platform):
            priority_label = PRIORITIES.get(priority_key, PRIORITIES["normal"])["label"]
            status_key = "new"
            status_label = STATUSES[status_key]

            caption_text = (
                f"🧵 {platform}\n\n"
                f"⚡ Priority: {priority_label}\n"
                f"📌 Status: {status_label}\n\n"
                f"🔗 Link:\n{url}\n\n"
                f"💭 Notes:\n{thought}\n\n"
                f"⚠️ Threads video download is currently disabled. Saved as link."
            )

            sent_message = await context.bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=topic_id,
                text=caption_text,
                reply_markup=build_post_action_keyboard(item_id)
            )

            success_caption = (
                f"✅ Threads пост сохранён как ссылка\n\n"
                f"{topic_icon} {topic}\n"
                f"⚡ Priority: {priority_label}\n"
                f"🎬 {platform}"
            )

            try:
                await query.edit_message_caption(caption=success_caption)
            except Exception:
                await query.edit_message_text(success_caption)

            db_item = {
                "id": item_id,
                "created_at": current_timestamp(),
                "updated_at": current_timestamp(),
                "type": "threads_link_reference",
                "topic": topic,
                "topic_id": topic_id,
                "topic_icon": topic_icon,
                "platform": platform,
                "url": url,
                "notes": thought,
                "priority": priority_key,
                "priority_label": priority_label,
                "status": status_key,
                "status_label": status_label,
                "reminder": None,
                "reminder_label": None,
                "chat_id": CHAT_ID,
                "message_id": sent_message.message_id if sent_message else None,
                "download_disabled": True
            }

            add_database_item(db_item)

        else:
            priority_label = PRIORITIES.get(priority_key, PRIORITIES["normal"])["label"]
            status_key = "new"
            status_label = STATUSES[status_key]

            loading_caption = (
                f"⏳ Скачиваю видео...\n\n"
                f"{topic_icon} {topic}\n"
                f"⚡ Priority: {priority_label}\n"
                f"🎬 {platform}"
            )

            try:
                await query.edit_message_caption(caption=loading_caption)
            except Exception:
                await query.edit_message_text(loading_caption)

            media_path = await download_video(url)

            caption_text = build_video_caption(
                platform,
                url,
                thought,
                priority_label,
                status_label
            )

            try:
                with open(media_path, "rb") as video_file:
                    sent_message = await context.bot.send_video(
                        chat_id=CHAT_ID,
                        message_thread_id=topic_id,
                        video=video_file,
                        caption=caption_text,
                        reply_markup=build_post_action_keyboard(item_id),
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=120
                    )
            except Exception as video_send_error:
                logger.error(
                    f"send_video failed, trying send_document: "
                    f"{type(video_send_error).__name__}: {repr(video_send_error)}"
                )

                with open(media_path, "rb") as doc_file:
                    sent_message = await context.bot.send_document(
                        chat_id=CHAT_ID,
                        message_thread_id=topic_id,
                        document=doc_file,
                        caption=caption_text,
                        reply_markup=build_post_action_keyboard(item_id),
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=120
                    )

            success_caption = (
                f"✅ Видео сохранено\n\n"
                f"{topic_icon} {topic}\n"
                f"⚡ Priority: {priority_label}\n"
                f"🎬 {platform}"
            )

            try:
                await query.edit_message_caption(caption=success_caption)
            except Exception:
                await query.edit_message_text(success_caption)

            db_item = {
                "id": item_id,
                "created_at": current_timestamp(),
                "updated_at": current_timestamp(),
                "type": "video_reference",
                "topic": topic,
                "topic_id": topic_id,
                "topic_icon": topic_icon,
                "platform": platform,
                "url": url,
                "notes": thought,
                "priority": priority_key,
                "priority_label": priority_label,
                "status": status_key,
                "status_label": status_label,
                "reminder": None,
                "reminder_label": None,
                "chat_id": CHAT_ID,
                "message_id": sent_message.message_id if sent_message else None
            }

            add_database_item(db_item)

        context.user_data.pop("content", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("selected_topic_icon", None)
        context.user_data.pop("selected_priority", None)
        clear_pending_content(user_id)

    except Exception as e:
        logger.error(f"Ошибка обработки медиа: {type(e).__name__}: {repr(e)}")

        try:
            if is_social_profile(url):
                fallback_text = build_profile_caption(url, thought, platform)

                sent_message = await context.bot.send_message(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    text=fallback_text
                )

                db_item = {
                    "id": item_id,
                    "created_at": current_timestamp(),
                    "updated_at": current_timestamp(),
                    "type": "profile_reference",
                    "topic": topic,
                    "topic_id": topic_id,
                    "topic_icon": topic_icon,
                    "platform": platform,
                    "username": extract_profile_username(url, platform),
                    "url": url,
                    "notes": thought,
                    "chat_id": CHAT_ID,
                    "message_id": sent_message.message_id if sent_message else None,
                    "media_failed": True
                }

                fail_caption = (
                    f"⚠️ Скриншот профиля не обработался, но профиль сохранён текстом.\n\n"
                    f"{topic_icon} {topic}\n"
                    f"🎬 {platform}"
                )

            else:
                priority_label = PRIORITIES.get(priority_key, PRIORITIES["normal"])["label"]
                status_key = "new"
                status_label = STATUSES[status_key]

                caption_text = build_video_caption(
                    platform,
                    url,
                    thought,
                    priority_label,
                    status_label
                )

                # X/Threads/Instagram photo posts may fail through yt-dlp.
                # In that case, save a screenshot of the post instead of only text.
                if should_screenshot_post_fallback(platform):
                    try:
                        screenshot_path = await make_profile_screenshot(url)

                        with open(screenshot_path, "rb") as photo_file:
                            sent_message = await context.bot.send_photo(
                                chat_id=CHAT_ID,
                                message_thread_id=topic_id,
                                photo=photo_file,
                                caption=caption_text,
                                reply_markup=build_post_action_keyboard(item_id),
                                read_timeout=120,
                                write_timeout=120,
                                connect_timeout=120
                            )

                        try:
                            if screenshot_path and os.path.exists(screenshot_path):
                                os.remove(screenshot_path)
                        except Exception:
                            pass

                        db_item = {
                            "id": item_id,
                            "created_at": current_timestamp(),
                            "updated_at": current_timestamp(),
                            "type": "post_screenshot_reference",
                            "topic": topic,
                            "topic_id": topic_id,
                            "topic_icon": topic_icon,
                            "platform": platform,
                            "url": url,
                            "notes": thought,
                            "priority": priority_key,
                            "priority_label": priority_label,
                            "status": status_key,
                            "status_label": status_label,
                            "reminder": None,
                            "reminder_label": None,
                            "chat_id": CHAT_ID,
                            "message_id": sent_message.message_id if sent_message else None,
                            "video_failed_screenshot_saved": True
                        }

                        fail_caption = (
                            f"⚠️ Видео не скачалось, но скриншот поста сохранён.\n\n"
                            f"{topic_icon} {topic}\n"
                            f"⚡ Priority: {priority_label}\n"
                            f"🎬 {platform}"
                        )

                    except Exception as screenshot_error:
                        logger.error(
                            f"Post screenshot fallback failed: "
                            f"{type(screenshot_error).__name__}: {repr(screenshot_error)}"
                        )

                        fallback_text = (
                            f"🎬 {platform}\n\n"
                            f"⚡ Priority: {priority_label}\n"
                            f"📌 Status: {status_label}\n\n"
                            f"🔗 Link:\n{url}\n\n"
                            f"💭 Notes:\n{thought}\n\n"
                            f"⚠️ Медиа и скриншот не удалось обработать автоматически. Сохраняю как ссылку."
                        )

                        sent_message = await context.bot.send_message(
                            chat_id=CHAT_ID,
                            message_thread_id=topic_id,
                            text=fallback_text,
                            reply_markup=build_post_action_keyboard(item_id)
                        )

                        db_item = {
                            "id": item_id,
                            "created_at": current_timestamp(),
                            "updated_at": current_timestamp(),
                            "type": "video_reference",
                            "topic": topic,
                            "topic_id": topic_id,
                            "topic_icon": topic_icon,
                            "platform": platform,
                            "url": url,
                            "notes": thought,
                            "priority": priority_key,
                            "priority_label": priority_label,
                            "status": status_key,
                            "status_label": status_label,
                            "reminder": None,
                            "reminder_label": None,
                            "chat_id": CHAT_ID,
                            "message_id": sent_message.message_id if sent_message else None,
                            "media_failed": True,
                            "screenshot_failed": True
                        }

                        fail_caption = (
                            f"⚠️ Видео и скриншот не обработались, но пост сохранён текстом.\n\n"
                            f"{topic_icon} {topic}\n"
                            f"⚡ Priority: {priority_label}\n"
                            f"🎬 {platform}"
                        )

                else:
                    fallback_text = (
                        f"🎬 {platform}\n\n"
                        f"⚡ Priority: {priority_label}\n"
                        f"📌 Status: {status_label}\n\n"
                        f"🔗 Link:\n{url}\n\n"
                        f"💭 Notes:\n{thought}\n\n"
                        f"⚠️ Медиа не удалось обработать автоматически. Сохраняю как ссылку."
                    )

                    sent_message = await context.bot.send_message(
                        chat_id=CHAT_ID,
                        message_thread_id=topic_id,
                        text=fallback_text,
                        reply_markup=build_post_action_keyboard(item_id)
                    )

                    db_item = {
                        "id": item_id,
                        "created_at": current_timestamp(),
                        "updated_at": current_timestamp(),
                        "type": "video_reference",
                        "topic": topic,
                        "topic_id": topic_id,
                        "topic_icon": topic_icon,
                        "platform": platform,
                        "url": url,
                        "notes": thought,
                        "priority": priority_key,
                        "priority_label": priority_label,
                        "status": status_key,
                        "status_label": status_label,
                        "reminder": None,
                        "reminder_label": None,
                        "chat_id": CHAT_ID,
                        "message_id": sent_message.message_id if sent_message else None,
                        "media_failed": True
                    }

                    fail_caption = (
                        f"⚠️ Видео не обработалось, но пост сохранён текстом.\n\n"
                        f"{topic_icon} {topic}\n"
                        f"⚡ Priority: {priority_label}\n"
                        f"🎬 {platform}"
                    )

            add_database_item(db_item)

            try:
                await query.edit_message_caption(caption=fail_caption)
            except Exception:
                await query.edit_message_text(fail_caption)

            context.user_data.pop("content", None)
            context.user_data.pop("selected_topic", None)
            context.user_data.pop("selected_topic_icon", None)
            context.user_data.pop("selected_priority", None)
            clear_pending_content(user_id)

        except Exception as send_error:
            logger.error(f"Ошибка fallback-отправки: {type(send_error).__name__}: {repr(send_error)}")
            await query.message.reply_text(f"❌ Ошибка: {send_error}")

    finally:
        context.application.bot_data.pop(f"processing_{user_id}", None)

        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception:
                pass

        queued = context.application.bot_data.pop(f"queued_{user_id}", None)

        if queued:
            try:
                await context.bot.delete_message(
                    chat_id=queued.get("chat_id"),
                    message_id=queued.get("message_id")
                )
            except Exception:
                pass

            try:
                await ask_topic_prompt_for_content(
                    context=context,
                    chat_id=queued.get("chat_id"),
                    user_id=user_id,
                    text=queued.get("content")
                )
            except Exception as queue_error:
                logger.error(
                    f"Не удалось открыть выбор топика для queued ссылки: "
                    f"{type(queue_error).__name__}: {repr(queue_error)}"
                )


# =========================
# UTILITY COMMANDS
# =========================

async def chat_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    thread_id = update.message.message_thread_id

    await update.message.reply_text(
        f"Chat ID: {chat.id}\n"
        f"Chat type: {chat.type}\n"
        f"Thread ID: {thread_id}"
    )


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookies_exists = Path(COOKIES_FILE).exists()
    topics = load_topics()
    database = load_database()
    reminders = load_reminders()

    await update.message.reply_text(
        f"Cookies file: {'✅ найден' if cookies_exists else '❌ не найден'}\n"
        f"Cookies path: {Path(COOKIES_FILE).resolve()}\n"
        f"Topics file: {Path(TOPICS_FILE).resolve()}\n"
        f"Topics count: {len(topics)}\n"
        f"Database file: {Path(DATABASE_FILE).resolve()}\n"
        f"Database items: {len(database)}\n"
        f"Reminders file: {Path(REMINDERS_FILE).resolve()}\n"
        f"Reminders count: {len(reminders)}\n"
        f"Download dir: {Path(DOWNLOAD_DIR).resolve()}\n"
        f"Docker mode: ✅ Playwright enabled"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {type(context.error).__name__}: {repr(context.error)}")


# =========================
# MAIN
# =========================

async def post_init(application):
    await application.bot.set_my_commands([
        ("start", "Open bot panel"),
        ("panel", "Show bottom panel"),
        ("topics", "Manage topics"),
        ("info", "About bot"),
        ("export", "Export database"),
        ("check", "Check bot status"),
        ("testreminder", "Preview reminder"),
        ("id", "Get chat ID"),
    ])

    if application.job_queue:
        application.job_queue.run_repeating(
            reminders_job,
            interval=30,
            first=10,
            name="reminders_job"
        )
        logger.info("Reminder job scheduled.")
    else:
        logger.warning(
            "JobQueue is not available. Install python-telegram-bot[job-queue] to enable reminders."
        )


def main():
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN не найден. Добавь BOT_TOKEN в Environment Variables на Render."
        )

    if not CHAT_ID:
        raise ValueError(
            "CHAT_ID не найден. Добавь CHAT_ID в Environment Variables на Render."
        )

    threading.Thread(target=run_web_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CommandHandler("hidepanel", hide_panel_cmd))
    app.add_handler(CommandHandler("testreminder", test_reminder_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("save", save_cmd))
    app.add_handler(CommandHandler("topics", topics_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("addtopic", add_topic_cmd))
    app.add_handler(CommandHandler("renametopic", rename_topic_cmd))
    app.add_handler(CommandHandler("deltopic", delete_topic_cmd))
    app.add_handler(CommandHandler("id", chat_id_cmd))
    app.add_handler(CommandHandler("check", check_cmd))

    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^(menu_|topics_|rename_select:|delete_select:|confirm_delete:|export_)"))
    app.add_handler(CallbackQueryHandler(save_priority_callback, pattern="^(save_priority_|cancel_save)"))
    app.add_handler(CallbackQueryHandler(post_action_callback, pattern="^post_"))
    app.add_handler(CallbackQueryHandler(on_topic, pattern="^(t_|cancel_save)"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
