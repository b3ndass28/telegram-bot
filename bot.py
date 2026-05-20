import logging
import json
import os
import re
import uuid
import csv
import asyncio
import threading
from pathlib import Path
from datetime import datetime

import yt_dlp
from flask import Flask
from playwright.async_api import async_playwright

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

PENDING_FILE = "pending.json"
TOPICS_FILE = "topics.json"
DATABASE_FILE = "database.json"
DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

ASSETS_DIR = "assets"
TOPICS_IMAGE = os.path.join(ASSETS_DIR, "topics.jpg")
INFO_IMAGE = os.path.join(ASSETS_DIR, "info.jpg")
EXPORT_IMAGE = os.path.join(ASSETS_DIR, "export.jpg")

Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


DEFAULT_TOPICS = {
    "CowGirl": {"id": 2, "icon": "🤠"},
    "Student": {"id": 6, "icon": "🎓"},
    "Meme": {"id": 7, "icon": "😂"},
    "Telegram": {"id": 4, "icon": "✈️"},
    "X": {"id": 8, "icon": "𝕏"},
    "Threads": {"id": 9, "icon": "🧵"},
    "Instagram": {"id": 22, "icon": "📸"}
}


PRIORITIES = {
    "high": {"label": "🔥 High", "short": "High"},
    "normal": {"label": "⭐ Normal", "short": "Normal"},
    "later": {"label": "🧊 Later", "short": "Later"}
}


STATUSES = {
    "new": "🆕 New",
    "progress": "🟡 In Progress",
    "done": "✅ Done",
    "bad": "❌ Not Suitable"
}


# =========================
# TOPIC HELPERS
# =========================

def load_topics():
    if os.path.exists(TOPICS_FILE):
        try:
            with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            fixed = {}

            for name, value in data.items():
                if isinstance(value, dict):
                    fixed[name] = {
                        "id": int(value.get("id")),
                        "icon": value.get("icon", "📂")
                    }
                else:
                    fixed[name] = {
                        "id": int(value),
                        "icon": "📂"
                    }

            return fixed

        except Exception as e:
            logger.error(f"Ошибка чтения topics.json: {e}")

    save_topics(DEFAULT_TOPICS)
    return DEFAULT_TOPICS.copy()


def save_topics(topics):
    try:
        with open(TOPICS_FILE, "w", encoding="utf-8") as f:
            json.dump(topics, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения topics.json: {e}")


def get_topic_names():
    return list(load_topics().keys())


def get_topic_id(name):
    topics = load_topics()
    item = topics.get(name)

    if not item:
        return None

    return item.get("id")


def get_topic_icon(name):
    topics = load_topics()
    item = topics.get(name)

    if not item:
        return "📂"

    return item.get("icon", "📂")


def guess_topic_icon(name):
    lower = name.lower()

    if "inst" in lower:
        return "📸"
    if "cow" in lower:
        return "🤠"
    if "student" in lower:
        return "🎓"
    if "meme" in lower:
        return "😂"
    if "telegram" in lower:
        return "✈️"
    if lower == "x" or "twitter" in lower:
        return "𝕏"
    if "thread" in lower:
        return "🧵"
    if "car" in lower or "auto" in lower:
        return "🏎️"
    if "idea" in lower:
        return "💡"
    if "ref" in lower:
        return "📌"

    return "📂"


def topics_text():
    topics = load_topics()

    if not topics:
        return "📂 Топиков пока нет."

    lines = ["📂 Текущие топики:\n"]

    for name, data in topics.items():
        icon = data.get("icon", "📂")
        topic_id = data.get("id")
        lines.append(f"{icon} {name} — ID: {topic_id}")

    return "\n".join(lines)


# =========================
# DATABASE HELPERS
# =========================

def load_database():
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                return data

        except Exception as e:
            logger.error(f"Ошибка чтения database.json: {e}")

    return []


def save_database(data):
    try:
        with open(DATABASE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения database.json: {e}")


def add_database_item(item):
    data = load_database()
    data.append(item)
    save_database(data)


def update_database_status(item_id, status):
    data = load_database()

    for item in data:
        if item.get("id") == item_id:
            item["status"] = status
            item["status_label"] = STATUSES.get(status, status)
            item["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_database(data)
            return item

    return None


def find_database_item(item_id):
    data = load_database()

    for item in data:
        if item.get("id") == item_id:
            return item

    return None


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


def safe_file_exists(path):
    return os.path.exists(path) and os.path.isfile(path)


async def send_photo_or_text_message(message, image_path, caption, reply_markup=None):
    if safe_file_exists(image_path):
        with open(image_path, "rb") as photo:
            await message.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=reply_markup
            )
    else:
        await message.reply_text(
            caption,
            reply_markup=reply_markup
        )


async def edit_or_send_photo(query, image_path, caption, reply_markup=None):
    try:
        await query.message.delete()
    except Exception:
        pass

    if safe_file_exists(image_path):
        with open(image_path, "rb") as photo:
            await query.message.chat.send_photo(
                photo=photo,
                caption=caption,
                reply_markup=reply_markup
            )
    else:
        await query.message.chat.send_message(
            caption,
            reply_markup=reply_markup
        )


def build_caption(platform, url, thought, priority_label, status_label):
    return (
        f"🎬 {platform}\n\n"
        f"⚡ Priority: {priority_label}\n"
        f"📌 Status: {status_label}\n\n"
        f"🔗 Link:\n{url}\n\n"
        f"💭 Notes:\n{thought}"
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
            KeyboardButton("✅ Check"),
            KeyboardButton("❌ Hide Panel")
        ]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
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
        [
            InlineKeyboardButton("➕ Создать новый", callback_data="topics_create")
        ],
        [
            InlineKeyboardButton("✏️ Изменить текущий", callback_data="topics_rename")
        ],
        [
            InlineKeyboardButton("🗑️ Удалить", callback_data="topics_delete")
        ],
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
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_priority_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔥 High", callback_data="priority_high"),
            InlineKeyboardButton("⭐ Normal", callback_data="priority_normal"),
            InlineKeyboardButton("🧊 Later", callback_data="priority_later")
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data="cancel")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def build_status_keyboard(item_id):
    keyboard = [
        [
            InlineKeyboardButton("🟡 В работе", callback_data=f"status_progress:{item_id}"),
            InlineKeyboardButton("✅ Сделано", callback_data=f"status_done:{item_id}")
        ],
        [
            InlineKeyboardButton("❌ Не подходит", callback_data=f"status_bad:{item_id}")
        ]
    ]

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
    logger.info("Проверяю Continue screen...")

    async def continue_still_visible():
        try:
            text = await page.locator("body").inner_text(timeout=3000)
            text_lower = text.lower()
            return "continue" in text_lower
        except Exception:
            return False

    async def wait_continue_disappear():
        for _ in range(8):
            if not await continue_still_visible():
                logger.info("Continue screen исчез.")
                return True
            await page.wait_for_timeout(1000)

        logger.warning("Continue screen всё еще виден после клика.")
        return False

    try:
        clicked = await page.evaluate(
            """
            () => {
                const candidates = Array.from(document.querySelectorAll(
                    'button, div[role="button"], a, span, div'
                ));

                function isVisible(el) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 &&
                           rect.height > 0 &&
                           style.visibility !== 'hidden' &&
                           style.display !== 'none';
                }

                for (const el of candidates) {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();

                    if (!text) continue;
                    if (!isVisible(el)) continue;

                    if (text.includes('continue')) {
                        const clickable = el.closest('button, div[role="button"], a') || el;

                        clickable.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                        clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        clickable.click();

                        return { clicked: true, text };
                    }
                }

                return { clicked: false };
            }
            """
        )

        if clicked and clicked.get("clicked"):
            logger.info(f"JS Continue click: {clicked}")
            await page.wait_for_timeout(3000)

            if await wait_continue_disappear():
                return True

    except Exception as e:
        logger.warning(f"JS Continue click failed: {type(e).__name__}: {repr(e)}")

    selectors = [
        "text=Continue",
        "text=Continue as",
        "button:has-text('Continue')",
        "div[role='button']:has-text('Continue')",
        "a:has-text('Continue')"
    ]

    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=2500, force=True)
            logger.info(f"Continue нажат через selector: {selector}")
            await page.wait_for_timeout(3000)

            if await wait_continue_disappear():
                return True

        except Exception:
            pass

    coordinate_clicks = [
        (195, 515),
        (195, 535),
        (195, 555),
        (195, 575),
        (195, 595),
        (195, 615),
    ]

    for x, y in coordinate_clicks:
        try:
            await page.mouse.click(x, y)
            logger.info(f"Continue fallback click: {x}, {y}")
            await page.wait_for_timeout(3000)

            if await wait_continue_disappear():
                return True

        except Exception:
            pass

    logger.warning("Continue не удалось нажать.")
    return False


async def close_instagram_popups(page):
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

    try:
        await page.mouse.click(358, 65)
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def wait_for_real_page_render(page):
    try:
        await page.wait_for_selector("body", timeout=15000)
    except Exception:
        pass

    try:
        await page.wait_for_function(
            """
            () => {
                const bodyText = document.body ? document.body.innerText.trim() : '';
                const imgs = document.querySelectorAll('img').length;
                const articles = document.querySelectorAll('article').length;
                const main = document.querySelector('main');

                return bodyText.length > 50 || imgs > 2 || articles > 0 || main;
            }
            """,
            timeout=20000
        )
        logger.info("Страница выглядит отрисованной.")
    except Exception as e:
        logger.warning(f"Не дождался полной отрисовки страницы: {type(e).__name__}: {repr(e)}")


async def goto_instagram_page(page, url, label):
    logger.info(f"Открываю страницу [{label}]: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.warning(f"goto warning [{label}]: {type(e).__name__}: {repr(e)}")

    await wait_for_real_page_render(page)
    await page.wait_for_timeout(5000)


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

            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(30000)

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

            logger.info("STEP 1: Открываю профиль впервые.")
            await goto_instagram_page(page, url, "profile-first")

            logger.info("STEP 2: Проверяю Continue.")
            did_continue = await click_continue_if_needed(page)

            if did_continue:
                logger.info("STEP 3: Continue был нажат. Открываю профиль заново.")
                await goto_instagram_page(page, url, "profile-after-continue")

            logger.info("STEP 4: Закрываю popup'ы.")
            await close_instagram_popups(page)
            await page.wait_for_timeout(2000)

            try:
                current_url = page.url.lower()
                logger.info(f"URL перед финальной проверкой: {current_url}")

                if (
                    "accounts" in current_url
                    or "login" in current_url
                    or "onetap" in current_url
                    or "challenge" in current_url
                ):
                    logger.info("Все еще login/accounts/challenge. Финально открываю профиль.")
                    await goto_instagram_page(page, url, "profile-final")
                    await close_instagram_popups(page)
                    await page.wait_for_timeout(2000)

            except Exception as e:
                logger.warning(f"Финальная проверка URL failed: {type(e).__name__}: {repr(e)}")

            logger.info("STEP 6: Догружаю профиль перед скрином.")

            await page.wait_for_timeout(4000)

            try:
                await page.mouse.wheel(0, 250)
                await page.wait_for_timeout(1000)
                await page.mouse.wheel(0, -250)
                await page.wait_for_timeout(1000)
            except Exception:
                pass

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
# EXPORT HELPERS
# =========================

def create_export_json():
    data = load_database()
    export_path = os.path.join(DOWNLOAD_DIR, "referens_database.json")

    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return export_path


def create_export_csv():
    data = load_database()
    export_path = os.path.join(DOWNLOAD_DIR, "referens_database.csv")

    fields = [
        "id",
        "created_at",
        "topic",
        "platform",
        "url",
        "notes",
        "priority",
        "status",
        "message_id",
        "chat_id"
    ]

    with open(export_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for item in data:
            writer.writerow({
                "id": item.get("id", ""),
                "created_at": item.get("created_at", ""),
                "topic": item.get("topic", ""),
                "platform": item.get("platform", ""),
                "url": item.get("url", ""),
                "notes": item.get("notes", ""),
                "priority": item.get("priority_label", item.get("priority", "")),
                "status": item.get("status_label", item.get("status", "")),
                "message_id": item.get("message_id", ""),
                "chat_id": item.get("chat_id", "")
            })

    return export_path


# =========================
# MENU HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋\n\n"
        "Отправь мне ссылку и мысли одним сообщением.\n\n"
        "Или открой панель:",
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
    text = (
        "ℹ️ Referens Bot\n\n"
        "Что умеет бот:\n\n"
        "1. Сохранять Instagram Reels / TikTok / YouTube ссылки.\n"
        "2. Скачивать видео через yt-dlp, если это возможно.\n"
        "3. Делать скрин Instagram-профиля через Playwright + cookies.\n"
        "4. Сохранять notes вместе с ссылкой.\n"
        "5. Выбирать топик через кнопки.\n"
        "6. Ставить priority: 🔥 High / ⭐ Normal / 🧊 Later.\n"
        "7. Менять status идеи: 🟡 In Progress / ✅ Done / ❌ Not Suitable.\n"
        "8. Управлять топиками через меню.\n"
        "9. Экспортировать базу в JSON или CSV.\n\n"
        "Как пользоваться:\n\n"
        "Отправь ссылку + заметку одним сообщением.\n"
        "Потом выбери топик и priority."
    )

    await send_photo_or_text_message(
        update.message,
        INFO_IMAGE,
        text,
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
    if len(context.args) < 2:
        await update.message.reply_text(
            "Используй так:\n\n"
            "/addtopic Название ID\n\n"
            "Пример:\n"
            "/addtopic Cars 25"
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
        f"✅ Топик добавлен:\n\n"
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

    topics[new_name] = topics.pop(old_name)
    topics[new_name]["icon"] = guess_topic_icon(new_name)

    save_topics(topics)

    await update.message.reply_text(
        f"✅ Топик переименован:\n\n"
        f"{old_name} → {topics[new_name]['icon']} {new_name}"
    )


async def delete_topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text(
            "Используй так:\n\n"
            "/deltopic Название\n\n"
            "Пример:\n"
            "/deltopic Cars"
        )
        return

    name = context.args[0].strip()

    topics = load_topics()

    if name not in topics:
        await update.message.reply_text(f"Топик {name} не найден.")
        return

    removed = topics.pop(name)
    save_topics(topics)

    await update.message.reply_text(
        f"🗑️ Топик удалён:\n\n"
        f"{name} — ID: {removed.get('id')}"
    )


# =========================
# CALLBACKS
# =========================

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "menu_main":
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)

        await query.edit_message_text(
            "⚙️ Главное меню\n\nЧто хочешь сделать?",
            reply_markup=build_main_menu_keyboard()
        )
        return

    if data == "menu_close":
        context.user_data.pop("mode", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("content", None)
        clear_pending_content(user_id)

        try:
            await query.edit_message_text("✅ Закрыто.")
        except Exception:
            await query.message.reply_text("✅ Закрыто.")
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
        text = (
            "ℹ️ Referens Bot\n\n"
            "Что умеет бот:\n\n"
            "1. Сохранять Instagram Reels / TikTok / YouTube ссылки.\n"
            "2. Скачивать видео через yt-dlp, если это возможно.\n"
            "3. Делать скрин Instagram-профиля через Playwright + cookies.\n"
            "4. Сохранять notes вместе с ссылкой.\n"
            "5. Выбирать топик через кнопки.\n"
            "6. Ставить priority: 🔥 High / ⭐ Normal / 🧊 Later.\n"
            "7. Менять status идеи.\n"
            "8. Управлять топиками через меню.\n"
            "9. Экспортировать базу в JSON или CSV."
        )

        await edit_or_send_photo(
            query,
            INFO_IMAGE,
            text,
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
        cookies_exists = os.path.exists(COOKIES_FILE)
        topics = load_topics()
        database = load_database()

        await query.edit_message_text(
            f"✅ Проверка бота\n\n"
            f"Cookies file: {'✅ найден' if cookies_exists else '❌ не найден'}\n"
            f"Topics count: {len(topics)}\n"
            f"Database items: {len(database)}\n"
            f"Docker mode: ✅ Playwright enabled",
            reply_markup=build_main_menu_keyboard()
        )
        return

    if data == "topics_create":
        context.user_data["mode"] = "awaiting_new_topic"

        await query.edit_message_text(
            "➕ Создание нового топика\n\n"
            "Отправь название и ID в таком формате:\n\n"
            "Cars 25\n\n"
            "Как узнать ID:\n"
            "1. Зайди в нужный топик группы\n"
            "2. Напиши /id\n"
            "3. Возьми Thread ID\n\n"
            "Доступные топики сейчас:\n\n"
            f"{topics_text()}",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if data == "topics_rename":
        context.user_data["mode"] = "select_rename_topic"

        await query.edit_message_text(
            "✏️ Выбери топик, который хочешь переименовать:",
            reply_markup=build_topic_select_keyboard("rename_select")
        )
        return

    if data == "topics_delete":
        context.user_data["mode"] = "select_delete_topic"

        await query.edit_message_text(
            "🗑️ Выбери топик, который хочешь удалить:",
            reply_markup=build_topic_select_keyboard("delete_select")
        )
        return

    if data.startswith("rename_select:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await query.edit_message_text(
                "Топик не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        context.user_data["mode"] = "awaiting_rename_topic"
        context.user_data["selected_topic"] = topic_name

        icon = topics[topic_name].get("icon", "📂")
        topic_id = topics[topic_name].get("id")

        await query.edit_message_text(
            f"✏️ Переименование топика\n\n"
            f"Текущий топик:\n"
            f"{icon} {topic_name} — ID: {topic_id}\n\n"
            f"Отправь новое название одним сообщением:",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    if data.startswith("delete_select:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await query.edit_message_text(
                "Топик не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        icon = topics[topic_name].get("icon", "📂")
        topic_id = topics[topic_name].get("id")

        await query.edit_message_text(
            f"⚠️ Точно удалить топик?\n\n"
            f"{icon} {topic_name} — ID: {topic_id}\n\n"
            f"Это удалит только кнопку из бота, сам Telegram-топик не удалится.",
            reply_markup=build_delete_confirm_keyboard(topic_name)
        )
        return

    if data.startswith("confirm_delete:"):
        topic_name = data.split(":", 1)[1]
        topics = load_topics()

        if topic_name not in topics:
            await query.edit_message_text(
                "Топик уже не найден.",
                reply_markup=build_topics_menu_keyboard()
            )
            return

        removed = topics.pop(topic_name)
        save_topics(topics)

        await query.edit_message_text(
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


async def priority_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "cancel":
        context.user_data.pop("content", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("selected_topic_icon", None)
        clear_pending_content(user_id)

        await query.edit_message_text(
            "❌ Отменено.\n\n"
            "Можешь отправить новую ссылку."
        )
        return

    priority_key = data.replace("priority_", "")
    priority = PRIORITIES.get(priority_key)

    if not priority:
        await query.edit_message_text("Ошибка: неизвестный priority.")
        return

    context.user_data["selected_priority"] = priority_key

    await save_selected_content(query, context)


async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    status_part, item_id = data.split(":", 1)
    status_key = status_part.replace("status_", "")

    status_label = STATUSES.get(status_key)

    if not status_label:
        await query.answer("Unknown status", show_alert=True)
        return

    item = update_database_status(item_id, status_key)

    if not item:
        await query.answer("Item not found in database", show_alert=True)
        return

    new_caption = build_caption(
        item.get("platform", "Unknown"),
        item.get("url", ""),
        item.get("notes", ""),
        item.get("priority_label", ""),
        item.get("status_label", status_label)
    )

    try:
        await query.edit_message_caption(
            caption=new_caption,
            reply_markup=build_status_keyboard(item_id)
        )
    except Exception as e:
        logger.error(f"Ошибка обновления caption/status: {type(e).__name__}: {repr(e)}")
        await query.answer("Status saved, but message caption was not updated", show_alert=True)


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

    if text == "❌ Hide Panel":
        await hide_panel_cmd(update, context)
        return

    if mode == "awaiting_new_topic":
        await handle_new_topic_text(update, context, text)
        return

    if mode == "awaiting_rename_topic":
        await handle_rename_topic_text(update, context, text)
        return

    await process_content(update, context, text)


async def handle_new_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    parts = text.split()

    if len(parts) < 2:
        await update.message.reply_text(
            "Нужно отправить название и ID.\n\n"
            "Пример:\n"
            "Cars 25",
            reply_markup=build_back_cancel_keyboard()
        )
        return

    name = parts[0].strip()
    topic_id_raw = parts[1].strip()

    try:
        topic_id = int(topic_id_raw)
    except ValueError:
        await update.message.reply_text(
            "ID должен быть числом.\n\n"
            "Пример:\n"
            "Cars 25",
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

    topics[name] = {
        "id": topic_id,
        "icon": guess_topic_icon(name)
    }

    save_topics(topics)

    context.user_data.pop("mode", None)

    await update.message.reply_text(
        f"✅ Топик добавлен:\n\n"
        f"{topics[name]['icon']} {name} — ID: {topic_id}\n\n"
        f"{topics_text()}",
        reply_markup=build_topics_menu_keyboard()
    )


async def handle_rename_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    old_name = context.user_data.get("selected_topic")
    new_name = text.strip().split()[0]

    if not old_name:
        context.user_data.pop("mode", None)
        await update.message.reply_text(
            "Ошибка: топик не выбран.",
            reply_markup=build_topics_menu_keyboard()
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


async def process_content(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not has_link(text):
        return

    user_id = update.effective_user.id

    context.user_data["content"] = text
    set_pending_content(user_id, text)

    if safe_file_exists(TOPICS_IMAGE):
        with open(TOPICS_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="📌 Куда сохранить?",
                reply_markup=build_topic_keyboard()
            )
    else:
        await update.message.reply_text(
            "📌 Куда сохранить?",
            reply_markup=build_topic_keyboard()
        )


async def on_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "cancel":
        context.user_data.pop("content", None)
        context.user_data.pop("selected_topic", None)
        context.user_data.pop("selected_topic_icon", None)
        clear_pending_content(user_id)

        await query.edit_message_text(
            "❌ Отменено.\n\n"
            "Можешь отправить новую ссылку."
        )
        return

    topic = query.data.replace("t_", "")

    if topic not in get_topic_names():
        await query.edit_message_text("Ошибка: неизвестный топик.")
        return

    context.user_data["selected_topic"] = topic
    context.user_data["selected_topic_icon"] = get_topic_icon(topic)

    topic_icon = get_topic_icon(topic)

    try:
        await query.edit_message_caption(
            caption=(
                f"{topic_icon} Topic: {topic}\n\n"
                f"⚡ Выбери priority:"
            ),
            reply_markup=build_priority_keyboard()
        )
    except Exception:
        await query.edit_message_text(
            f"{topic_icon} Topic: {topic}\n\n"
            f"⚡ Выбери priority:",
            reply_markup=build_priority_keyboard()
        )


async def save_selected_content(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id

    content = context.user_data.get("content") or get_pending_content(user_id)
    topic = context.user_data.get("selected_topic")
    priority_key = context.user_data.get("selected_priority", "normal")

    if not content:
        await query.edit_message_text(
            "Ошибка: контент не найден. Отправь ссылку заново."
        )
        return

    if not topic:
        await query.edit_message_text(
            "Ошибка: топик не выбран. Отправь ссылку заново."
        )
        return

    url, thought = extract_url_and_thought(content)

    if not url:
        await query.edit_message_text("Ошибка: ссылка не найдена.")
        return

    platform = detect_platform(url)
    topic_id = get_topic_id(topic)
    topic_icon = get_topic_icon(topic)
    priority_label = PRIORITIES.get(priority_key, PRIORITIES["normal"])["label"]
    status_key = "new"
    status_label = STATUSES[status_key]

    item_id = str(uuid.uuid4())

    caption_text = build_caption(
        platform,
        url,
        thought,
        priority_label,
        status_label
    )

    media_path = None
    sent_message = None

    try:
        if is_instagram_profile(url):
            await query.edit_message_caption(
                caption=(
                    f"📸 Делаю скрин профиля...\n\n"
                    f"{topic_icon} {topic}\n"
                    f"⚡ Priority: {priority_label}\n"
                    f"🎬 {platform}"
                )
            )

            media_path = await make_instagram_profile_screenshot(url)

            with open(media_path, "rb") as photo_file:
                sent_message = await context.bot.send_photo(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    photo=photo_file,
                    caption=caption_text,
                    reply_markup=build_status_keyboard(item_id),
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

            await query.edit_message_caption(
                caption=(
                    f"✅ Скрин профиля сохранен\n\n"
                    f"{topic_icon} {topic}\n"
                    f"⚡ Priority: {priority_label}\n"
                    f"🎬 {platform}"
                )
            )

        else:
            await query.edit_message_caption(
                caption=(
                    f"⏳ Скачиваю видео...\n\n"
                    f"{topic_icon} {topic}\n"
                    f"⚡ Priority: {priority_label}\n"
                    f"🎬 {platform}"
                )
            )

            media_path = await download_video(url)

            with open(media_path, "rb") as video_file:
                sent_message = await context.bot.send_video(
                    chat_id=CHAT_ID,
                    message_thread_id=topic_id,
                    video=video_file,
                    caption=caption_text,
                    reply_markup=build_status_keyboard(item_id),
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120
                )

            await query.edit_message_caption(
                caption=(
                    f"✅ Видео сохранено\n\n"
                    f"{topic_icon} {topic}\n"
                    f"⚡ Priority: {priority_label}\n"
                    f"🎬 {platform}"
                )
            )

        db_item = {
            "id": item_id,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

        fallback_text = (
            f"🎬 {platform}\n\n"
            f"⚡ Priority: {priority_label}\n"
            f"📌 Status: {status_label}\n\n"
            f"🔗 Link:\n{url}\n\n"
            f"💭 Notes:\n{thought}\n\n"
            f"⚠️ Медиа не удалось обработать автоматически."
        )

        try:
            sent_message = await context.bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=topic_id,
                text=fallback_text,
                reply_markup=build_status_keyboard(item_id)
            )

            db_item = {
                "id": item_id,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
                "chat_id": CHAT_ID,
                "message_id": sent_message.message_id if sent_message else None,
                "media_failed": True
            }

            add_database_item(db_item)

            try:
                await query.edit_message_caption(
                    caption=(
                        f"⚠️ Медиа не обработалось, но пост сохранен текстом.\n\n"
                        f"{topic_icon} {topic}\n"
                        f"⚡ Priority: {priority_label}\n"
                        f"🎬 {platform}"
                    )
                )
            except Exception:
                await query.edit_message_text(
                    f"⚠️ Медиа не обработалось, но пост сохранен текстом.\n\n"
                    f"{topic_icon} {topic}\n"
                    f"⚡ Priority: {priority_label}\n"
                    f"🎬 {platform}"
                )

            context.user_data.pop("content", None)
            context.user_data.pop("selected_topic", None)
            context.user_data.pop("selected_topic_icon", None)
            context.user_data.pop("selected_priority", None)
            clear_pending_content(user_id)

        except Exception as send_error:
            logger.error(f"Ошибка fallback-отправки: {type(send_error).__name__}: {repr(send_error)}")
            await query.message.reply_text(f"❌ Ошибка: {send_error}")

    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception:
                pass


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
    cookies_exists = os.path.exists(COOKIES_FILE)
    topics = load_topics()
    database = load_database()

    await update.message.reply_text(
        f"Cookies file: {'✅ найден' if cookies_exists else '❌ не найден'}\n"
        f"Cookies path: {os.path.abspath(COOKIES_FILE)}\n"
        f"Topics file: {os.path.abspath(TOPICS_FILE)}\n"
        f"Topics count: {len(topics)}\n"
        f"Database file: {os.path.abspath(DATABASE_FILE)}\n"
        f"Database items: {len(database)}\n"
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
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CommandHandler("hidepanel", hide_panel_cmd))
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
    app.add_handler(CallbackQueryHandler(priority_callback, pattern="^(priority_|cancel)"))
    app.add_handler(CallbackQueryHandler(status_callback, pattern="^status_"))
    app.add_handler(CallbackQueryHandler(on_topic, pattern="^(t_|cancel)"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
