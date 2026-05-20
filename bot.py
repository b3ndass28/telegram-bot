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
from playwright.async_api import async_playwright

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

CHAT_ID = -1003794802790

TOPICS = [
    "CowGirl",
    "Student",
    "Meme",
    "Telegram",
    "X",
    "Threads",
    "Instagram"
]

PENDING_FILE = "pending.json"
DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


# =========================
# FILE HELPERS
# =========================

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
        "Threads": 9,
        "Instagram": 22
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


def detect_platform(url: str) -> str:
    url_lower = url.lower()

    if "instagram.com" in url_lower:
        if "/reel/" in url_lower or "/reels/" in url_lower:
            return "Instagram Reel"
        if "/p/" in url_lower:
            return "Instagram Post"
        if "/stories/" in url_lower:
            return "Instagram Story"
        return "Instagram Profile"

    if "tiktok.com" in url_lower or "vm.tiktok.com" in url_lower:
        return "TikTok"

    if "youtube.com/shorts" in url_lower:
        return "YouTube Shorts"

    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"

    if "x.com" in url_lower or "twitter.com" in url_lower:
        return "X / Twitter"

    if "threads.net" in url_lower:
        return "Threads"

    return "Video"


def is_instagram_profile(url: str) -> bool:
    url_lower = url.lower()

    if "instagram.com" not in url_lower:
        return False

    not_profile_parts = [
        "/reel/",
        "/reels/",
        "/p/",
        "/stories/",
        "/tv/",
        "/explore/",
        "/accounts/",
        "/direct/"
    ]

    return not any(part in url_lower for part in not_profile_parts)


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
# COOKIES FOR PLAYWRIGHT
# =========================

def load_netscape_cookies_for_playwright(cookie_file: str):
    cookies = []

    if not os.path.exists(cookie_file):
        logger.warning("cookies.txt не найден для Playwright.")
        return cookies

    try:
        with open(cookie_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")

            if len(parts) < 7:
                continue

            domain, flag, path, secure, expiration, name, value = parts[:7]

            try:
                expires = int(expiration)
            except Exception:
                expires = -1

            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": expires,
                "httpOnly": False,
                "secure": secure.upper() == "TRUE",
                "sameSite": "Lax"
            }

            cookies.append(cookie)

        logger.info(f"Загружено cookies для Playwright: {len(cookies)}")
        return cookies

    except Exception as e:
        logger.error(f"Ошибка чтения cookies.txt для Playwright: {e}")
        return []


# =========================
# VIDEO DOWNLOAD WITH YT-DLP
# =========================

def download_video_sync(url: str):
    video_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "max_filesize": 48 * 1024 * 1024,
        "merge_output_format": "mp4",
    }

    if os.path.exists(COOKIES_FILE):
        logger.info("cookies.txt найден. Использую cookies для yt-dlp.")
        ydl_opts["cookiefile"] = COOKIES_FILE
    else:
        logger.warning("cookies.txt не найден. Instagram может не скачаться.")

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
# SCREENSHOT WITH PLAYWRIGHT
# =========================

async def close_instagram_popups(page):
    """
    Пытается закрыть Instagram popup окна:
    Save your login info, Not now, cookies, крестик и другие модалки.
    """

    # 1. Пробуем закрыть по тексту кнопок
    popup_texts = [
        "Not now",
        "Not Now",
        "Not now.",
        "Maybe later",
        "Allow all cookies",
        "Accept all",
        "Accept",
        "Save info",
        "Save your login info?"
    ]

    for text in popup_texts:
        try:
            await page.get_by_text(text, exact=False).click(timeout=2500)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    # 2. Отдельно пробуем locator по тексту Not now
    try:
        await page.locator("text=Not now").click(timeout=3000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    try:
        await page.locator("text=Not Now").click(timeout=3000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    # 3. Пробуем role button
    try:
        await page.get_by_role("button", name=re.compile("Not now", re.I)).click(timeout=3000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    try:
        await page.get_by_role("button", name=re.compile("Not Now", re.I)).click(timeout=3000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    # 4. Пробуем Escape
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # 5. Пробуем кликнуть по крестику справа сверху.
    # Viewport 390x844 с device_scale_factor=2.
    # Координаты клика в CSS px, поэтому крестик примерно справа сверху: x=358, y=65.
    possible_close_points = [
        (358, 65),
        (360, 70),
        (350, 60),
        (365, 58)
    ]

    for x, y in possible_close_points:
        try:
            await page.mouse.click(x, y)
            await page.wait_for_timeout(1500)
        except Exception:
            pass


async def make_instagram_profile_screenshot(url: str):
    screenshot_id = str(uuid.uuid4())
    screenshot_path = os.path.join(DOWNLOAD_DIR, f"{screenshot_id}.png")

    cookies = load_netscape_cookies_for_playwright(COOKIES_FILE)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            )
        )

        if cookies:
            await context.add_cookies(cookies)
            logger.info("Cookies добавлены в Playwright context.")
        else:
            logger.warning("Cookies не добавлены в Playwright context.")

        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(7000)

        # Закрываем popup'ы несколько раз, потому что Instagram иногда показывает их не сразу
        await close_instagram_popups(page)
        await page.wait_for_timeout(2000)
        await close_instagram_popups(page)

        # Небольшая прокрутка вниз-вверх, чтобы профиль догрузился
        try:
            await page.mouse.wheel(0, 300)
            await page.wait_for_timeout(1500)
            await page.mouse.wheel(0, -300)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        await page.wait_for_timeout(3000)

        await page.screenshot(
            path=screenshot_path,
            full_page=False
        )

        await browser.close()

    return screenshot_path


# =========================
# BOT HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Отправь мне ссылку и мысли одним сообщением.\n\n"
        "Примеры:\n"
        "https://www.instagram.com/reel/... идея для поста\n\n"
        "https://www.instagram.com/username/ реф аккаунт по вайбу"
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
    # Если пользователь отправил текст без ссылки — бот молчит
    if not has_link(text):
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

    platform = detect_platform(url)
    topic_id = get_topic_id(topic)

    caption_text = (
        f"🎬 {platform}\n\n"
        f"🔗 Link:\n{url}\n\n"
        f"💭 Notes:\n{thought}"
    )

    media_path = None

    try:
        if is_instagram_profile(url):
            await query.edit_message_text(
                f"📸 Делаю скрин профиля...\n\n"
                f"📂 {topic}\n"
                f"🎬 {platform}"
            )

            media_path = await make_instagram_profile_screenshot(url)

            with open(media_path, "rb") as photo_file:
                if topic_id is not None:
                    await context.bot.send_photo(
                        chat_id=CHAT_ID,
                        message_thread_id=topic_id,
                        photo=photo_file,
                        caption=caption_text,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=120
                    )
                else:
                    await context.bot.send_photo(
                        chat_id=CHAT_ID,
                        photo=photo_file,
                        caption=caption_text,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=120
                    )

            await query.edit_message_text(
                f"✅ Скрин профиля сохранен\n\n"
                f"📂 {topic}\n"
                f"🎬 {platform}"
            )

        else:
            await query.edit_message_text(
                f"⏳ Скачиваю видео...\n\n"
                f"📂 {topic}\n"
                f"🎬 {platform}"
            )

            media_path = await download_video(url)

            with open(media_path, "rb") as video_file:
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
                f"📂 {topic}\n"
                f"🎬 {platform}"
            )

        context.user_data.pop("content", None)
        clear_pending_content(user_id)

    except Exception as e:
        logger.error(f"Ошибка обработки медиа: {e}")

        fallback_text = (
            f"🎬 {platform}\n\n"
            f"🔗 Link:\n{url}\n\n"
            f"💭 Notes:\n{thought}\n\n"
            f"⚠️ Медиа не удалось обработать автоматически."
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
                f"⚠️ Медиа не обработалось, но пост сохранен текстом.\n\n"
                f"📂 {topic}\n"
                f"🎬 {platform}"
            )

            context.user_data.pop("content", None)
            clear_pending_content(user_id)

        except Exception as send_error:
            logger.error(f"Ошибка fallback-отправки: {send_error}")
            await query.edit_message_text(f"❌ Ошибка: {send_error}")

    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
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


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookies_exists = os.path.exists(COOKIES_FILE)

    await update.message.reply_text(
        f"Cookies file: {'✅ найден' if cookies_exists else '❌ не найден'}\n"
        f"Cookies path: {os.path.abspath(COOKIES_FILE)}\n"
        f"Pending file: {os.path.abspath(PENDING_FILE)}\n"
        f"Download dir: {os.path.abspath(DOWNLOAD_DIR)}\n"
        f"Docker mode: ✅ Playwright enabled"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN не найден. Добавь BOT_TOKEN в Environment Variables на Render."
        )

    threading.Thread(target=run_web_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("save", save_cmd))
    app.add_handler(CommandHandler("id", chat_id_cmd))
    app.add_handler(CommandHandler("check", check_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_handler(CallbackQueryHandler(on_topic, pattern="^(t_|cancel)"))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
