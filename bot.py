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

            if not line or line.startswith("# Netscape"):
                continue

            http_only = False

            if line.startswith("#HttpOnly_"):
                http_only = True
                line = line.replace("#HttpOnly_", "", 1)

            if line.startswith("#"):
                continue

            parts = line.split("\t")

            if len(parts) < 7:
                continue

            domain, flag, path, secure, expiration, name, value = parts[:7]

            try:
                expires = int(expiration)
            except Exception:
                expires = -1

            if expires == 0:
                expires = -1

            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": expires,
                "httpOnly": http_only,
                "secure": secure.upper() == "TRUE",
                "sameSite": "Lax"
            }

            cookies.append(cookie)

        logger.info(f"Загружено cookies для Playwright: {len(cookies)}")
        return cookies

    except Exception as e:
        logger.error(f"Ошибка чтения cookies.txt для Playwright: {type(e).__name__}: {repr(e)}")
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
# INSTAGRAM SCREENSHOT HELPERS
# =========================

async def js_click_by_text(page, words):
    """
    Ищет видимый элемент по тексту и кликает через JS.
    """
    try:
        result = await page.evaluate(
            """
            (words) => {
                const targets = words.map(w => w.toLowerCase());

                function isVisible(el) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 &&
                           rect.height > 0 &&
                           style.visibility !== 'hidden' &&
                           style.display !== 'none';
                }

                const candidates = Array.from(document.querySelectorAll(
                    'button, div[role="button"], a, span, div'
                ));

                for (const el of candidates) {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();

                    if (!text) continue;
                    if (!isVisible(el)) continue;

                    for (const target of targets) {
                        if (text.includes(target)) {
                            const clickable = el.closest('button, div[role="button"], a') || el;
                            clickable.click();
                            return { clicked: true, text };
                        }
                    }
                }

                return { clicked: false, text: null };
            }
            """,
            words
        )

        if result and result.get("clicked"):
            logger.info(f"JS click сработал: {result.get('text')}")
            await page.wait_for_timeout(2500)
            return True

    except Exception as e:
        logger.warning(f"JS click failed: {type(e).__name__}: {repr(e)}")

    return False


async def click_continue_if_needed(page):
    """
    Жестко нажимает Continue / Continue as.
    Использует JS, selectors, role и координаты.
    """

    logger.info("Проверяю Continue screen...")

    # 1. JS по тексту
    clicked = await js_click_by_text(page, ["Continue as", "Continue"])
    if clicked:
        logger.info("Continue нажат через JS.")
        return True

    # 2. Selectors
    selectors = [
        "text=Continue",
        "text=Continue as",
        "button:has-text('Continue')",
        "div[role='button']:has-text('Continue')",
        "a:has-text('Continue')"
    ]

    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=1500)
            logger.info(f"Continue нажат через selector: {selector}")
            await page.wait_for_timeout(2500)
            return True
        except Exception:
            pass

    # 3. Role button
    try:
        await page.get_by_role("button", name=re.compile("Continue", re.I)).click(timeout=1500)
        logger.info("Continue нажат через role button.")
        await page.wait_for_timeout(2500)
        return True
    except Exception:
        pass

    # 4. Координатный fallback
    # На viewport 390x844 кнопка Continue обычно по центру, примерно y=560-620
    coordinate_clicks = [
        (195, 585),
        (195, 610),
        (195, 560),
        (195, 535),
    ]

    for x, y in coordinate_clicks:
        try:
            await page.mouse.click(x, y)
            logger.info(f"Continue fallback click по координатам: {x}, {y}")
            await page.wait_for_timeout(2500)
            return True
        except Exception:
            pass

    logger.info("Continue не найден.")
    return False


async def close_instagram_popups(page):
    """
    Быстро закрывает обычные Instagram popup'ы.
    """

    logger.info("Закрываю Instagram popup'ы...")

    popup_words = [
        "Not now",
        "Not Now",
        "Maybe later",
        "Allow all cookies",
        "Accept all",
        "Accept",
        "Save info",
        "Save your login info"
    ]

    await js_click_by_text(page, popup_words)

    selectors = [
        "text=Not now",
        "text=Not Now",
        "text=Maybe later",
        "text=Allow all cookies",
        "text=Accept all",
        "text=Accept"
    ]

    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=1000)
            logger.info(f"Popup закрыт через selector: {selector}")
            await page.wait_for_timeout(500)
        except Exception:
            pass

    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    # Крестик справа сверху
    try:
        await page.mouse.click(358, 65)
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def make_instagram_profile_screenshot(url: str):
    screenshot_id = str(uuid.uuid4())
    screenshot_path = os.path.join(DOWNLOAD_DIR, f"{screenshot_id}.png")

    cookies = load_netscape_cookies_for_playwright(COOKIES_FILE)

    browser = None

    async with async_playwright() as p:
        try:
            logger.info("Запускаю Chromium...")

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            context = await browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                )
            )

            context.set_default_timeout(6000)
            context.set_default_navigation_timeout(12000)

            if cookies:
                await context.add_cookies(cookies)
                logger.info(f"Cookies добавлены в Playwright context: {len(cookies)}")
            else:
                logger.warning("Cookies не добавлены в Playwright context.")

            page = await context.new_page()

            try:
                await page.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    """
                )
            except Exception:
                pass

            # STEP 1: открыть профиль сразу
            logger.info(f"STEP 1: Открываю профиль: {url}")

            try:
                await page.goto(url, wait_until="commit", timeout=12000)
            except Exception as e:
                logger.warning(f"Первый goto profile warning: {type(e).__name__}: {repr(e)}")

            await page.wait_for_timeout(4000)

            # STEP 2: если появился Continue screen — нажимаем
            logger.info("STEP 2: Проверяю Continue на первом экране.")

            did_continue = await click_continue_if_needed(page)

            # STEP 3: если нажали Continue — открываем профиль заново
            if did_continue:
                logger.info("STEP 3: Continue был нажат. Открываю профиль заново.")

                try:
                    await page.goto(url, wait_until="commit", timeout=12000)
                except Exception as e:
                    logger.warning(f"Второй goto profile warning: {type(e).__name__}: {repr(e)}")

                await page.wait_for_timeout(5000)

            # STEP 4: закрываем popup'ы
            logger.info("STEP 4: Закрываю popup'ы.")

            await close_instagram_popups(page)
            await page.wait_for_timeout(1500)

            # STEP 5: если после popup всё еще не профиль, пробуем еще раз открыть профиль
            try:
                current_url = page.url.lower()
                logger.info(f"URL перед финальной проверкой: {current_url}")

                if "accounts" in current_url or "login" in current_url or "onetap" in current_url or "challenge" in current_url:
                    logger.info("Все еще login/accounts/challenge. Финально открываю профиль.")

                    try:
                        await page.goto(url, wait_until="commit", timeout=12000)
                    except Exception as e:
                        logger.warning(f"Финальный goto profile warning: {type(e).__name__}: {repr(e)}")

                    await page.wait_for_timeout(5000)
                    await close_instagram_popups(page)

            except Exception as e:
                logger.warning(f"Финальная проверка URL failed: {type(e).__name__}: {repr(e)}")

            # STEP 6: маленький скролл
            try:
                await page.mouse.wheel(0, 250)
                await page.wait_for_timeout(500)
                await page.mouse.wheel(0, -250)
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # STEP 7: скрин
            logger.info("STEP 7: Делаю screenshot.")

            await page.screenshot(
                path=screenshot_path,
                full_page=False
            )

            return screenshot_path

        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass


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

            media_path = await asyncio.wait_for(
                make_instagram_profile_screenshot(url),
                timeout=90
            )

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
        logger.error(f"Ошибка обработки медиа: {type(e).__name__}: {repr(e)}")

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
            logger.error(f"Ошибка fallback-отправки: {type(send_error).__name__}: {repr(send_error)}")
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
    logger.error(f"Update {update} caused error: {type(context.error).__name__}: {repr(context.error)}")


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
