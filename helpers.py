import asyncio
import csv
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import yt_dlp
from playwright.async_api import async_playwright

from config import (
    DEFAULT_TOPICS,
    TOPICS_FILE,
    DATABASE_FILE,
    REMINDERS_FILE,
    PENDING_FILE,
    DOWNLOAD_DIR,
    COOKIES_FILE,
    PRIORITIES,
    STATUSES,
)

logger = logging.getLogger(__name__)


# =========================
# JSON / STORAGE
# =========================

def load_json_file(path, default):
    path = Path(path)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения {path}: {type(e).__name__}: {repr(e)}")
    return default


def save_json_file(path, data):
    path = Path(path)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения {path}: {type(e).__name__}: {repr(e)}")


# =========================
# TOPICS
# =========================

def load_topics():
    data = load_json_file(TOPICS_FILE, None)

    if not data:
        save_topics(DEFAULT_TOPICS)
        return DEFAULT_TOPICS.copy()

    fixed = {}

    try:
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
        logger.error(f"Ошибка нормализации topics.json: {type(e).__name__}: {repr(e)}")
        save_topics(DEFAULT_TOPICS)
        return DEFAULT_TOPICS.copy()


def save_topics(topics):
    save_json_file(TOPICS_FILE, topics)


def get_topic_names():
    return list(load_topics().keys())


def get_topic_id(name):
    item = load_topics().get(name)
    return item.get("id") if item else None


def get_topic_icon(name):
    item = load_topics().get(name)
    return item.get("icon", "📂") if item else "📂"


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
        lines.append(f"{data.get('icon', '📂')} {name} — ID: {data.get('id')}")
    return "\n".join(lines)


# =========================
# DATABASE
# =========================

def load_database():
    data = load_json_file(DATABASE_FILE, [])
    return data if isinstance(data, list) else []


def save_database(data):
    save_json_file(DATABASE_FILE, data)


def add_database_item(item):
    data = load_database()
    data.append(item)
    save_database(data)


def find_database_item(item_id):
    for item in load_database():
        if item.get("id") == item_id:
            return item
    return None


def update_database_item(item_id, updates):
    data = load_database()
    for item in data:
        if item.get("id") == item_id:
            item.update(updates)
            item["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_database(data)
            return item
    return None


# =========================
# REMINDERS
# =========================

def load_reminders():
    data = load_json_file(REMINDERS_FILE, [])
    return data if isinstance(data, list) else []


def save_reminders(data):
    save_json_file(REMINDERS_FILE, data)


def add_reminder(item_id, user_id, due_ts, label):
    reminders = load_reminders()

    reminder = {
        "id": str(uuid.uuid4()),
        "item_id": item_id,
        "user_id": user_id,
        "due_ts": due_ts,
        "label": label,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sent": False
    }

    reminders.append(reminder)
    save_reminders(reminders)
    return reminder


def remove_active_reminders_for_item(item_id):
    reminders = load_reminders()
    changed = False

    for reminder in reminders:
        if reminder.get("item_id") == item_id and not reminder.get("sent"):
            reminder["sent"] = True
            reminder["cancelled"] = True
            reminder["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            changed = True

    if changed:
        save_reminders(reminders)

    return changed


def build_reminder_text(item):
    return (
        f"🔔 Reminder\n\n"
        f"Пора вернуться к идее:\n\n"
        f"🎬 {item.get('platform', '')}\n"
        f"⚡ Priority: {item.get('priority_label', '')}\n"
        f"📌 Status: {item.get('status_label', '')}\n\n"
        f"🔗 Link:\n{item.get('url', '')}\n\n"
        f"💭 Notes:\n{item.get('notes', '')}"
    )


async def reminders_job(context):
    """
    One reminder check. Scheduled by Telegram JobQueue.
    This replaces the old infinite reminders_loop task, which could be destroyed while pending.
    """
    try:
        now = time.time()
        reminders = load_reminders()
        changed = False

        for reminder in reminders:
            if reminder.get("sent"):
                continue

            if reminder.get("due_ts", 0) <= now:
                item = find_database_item(reminder.get("item_id"))

                if item:
                    user_id = reminder.get("user_id")

                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=build_reminder_text(item)
                        )

                        if item.get("chat_id") and item.get("message_id"):
                            try:
                                await context.bot.copy_message(
                                    chat_id=user_id,
                                    from_chat_id=item.get("chat_id"),
                                    message_id=item.get("message_id")
                                )
                            except Exception as copy_error:
                                logger.error(
                                    f"Не удалось скопировать оригинальный пост в reminder: "
                                    f"{type(copy_error).__name__}: {repr(copy_error)}"
                                )

                    except Exception as e:
                        logger.error(f"Не удалось отправить reminder: {type(e).__name__}: {repr(e)}")

                    updated_item = update_database_item(item.get("id"), {
                        "reminder": "finished",
                        "reminder_label": "✅ Reminder finished"
                    })

                    if updated_item and updated_item.get("type") in {
                        "video_reference",
                        "post_screenshot_reference",
                        "threads_link_reference"
                    }:
                        try:
                            await context.bot.edit_message_caption(
                                chat_id=updated_item.get("chat_id"),
                                message_id=updated_item.get("message_id"),
                                caption=build_video_caption(
                                    updated_item.get("platform", ""),
                                    updated_item.get("url", ""),
                                    updated_item.get("notes", ""),
                                    updated_item.get("priority_label", ""),
                                    updated_item.get("status_label", ""),
                                    updated_item.get("reminder_label")
                                )
                            )
                        except Exception as edit_error:
                            logger.error(
                                f"Не удалось обновить caption после reminder: "
                                f"{type(edit_error).__name__}: {repr(edit_error)}"
                            )

                reminder["sent"] = True
                reminder["sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                changed = True

        if changed:
            save_reminders(reminders)

    except Exception as e:
        logger.error(f"Ошибка reminder job: {type(e).__name__}: {repr(e)}")


# =========================
# PENDING
# =========================

def load_pending():
    data = load_json_file(PENDING_FILE, {})
    return data if isinstance(data, dict) else {}


def save_pending(data):
    save_json_file(PENDING_FILE, data)


def set_pending_content(user_id, content):
    data = load_pending()
    data[str(user_id)] = content
    save_pending(data)


def get_pending_content(user_id):
    return load_pending().get(str(user_id))


def clear_pending_content(user_id):
    data = load_pending()
    data.pop(str(user_id), None)
    save_pending(data)


# =========================
# TEXT / URL HELPERS
# =========================

def has_link(text: str) -> bool:
    return "http://" in text or "https://" in text


def clean_url(url: str) -> str:
    return url.strip().rstrip(").,]")


def extract_url_and_thought(text: str):
    url_match = re.search(r"https?://\S+", text)

    if not url_match:
        return None, text.strip()

    raw_url = url_match.group(0)
    url = clean_url(raw_url)
    thought = text.replace(raw_url, "", 1).strip()

    if not thought:
        thought = "Без заметки"

    return url, thought


def normalize_instagram_url(url: str) -> str:
    url = clean_url(url)

    if "instagram.com" not in url.lower():
        return url

    url = url.split("?")[0].split("#")[0]

    if not url.endswith("/"):
        url += "/"

    return url


def normalize_threads_url(url: str) -> str:
    """
    Threads often shares links as threads.com/.../media.
    yt-dlp expects threads.net and the post URL, not the /media suffix.
    """
    url = clean_url(url).split("?")[0].split("#")[0]
    url = url.replace("https://www.threads.com/", "https://www.threads.net/")
    url = url.replace("http://www.threads.com/", "https://www.threads.net/")
    url = url.replace("https://threads.com/", "https://www.threads.net/")
    url = url.replace("http://threads.com/", "https://www.threads.net/")

    if url.endswith("/media"):
        url = url[:-6]

    if "/media/" in url:
        url = url.split("/media/")[0]

    return url


def extract_instagram_username(url: str):
    url = normalize_instagram_url(url)
    match = re.search(r"instagram\.com/([^/?#]+)/?", url, re.I)

    if not match:
        return None

    username = match.group(1).strip()

    blocked = {
        "reel",
        "reels",
        "p",
        "stories",
        "tv",
        "explore",
        "accounts",
        "direct"
    }

    if username.lower() in blocked:
        return None

    return username


def extract_tiktok_username(url: str):
    match = re.search(r"tiktok\.com/@([^/?#]+)", url, re.I)
    if not match:
        return None
    return match.group(1).strip()


def is_tiktok_profile(url: str) -> bool:
    url_lower = url.lower()

    if "tiktok.com/@" not in url_lower:
        return False

    video_parts = [
        "/video/",
        "/photo/",
        "/t/",
        "/embed/"
    ]

    return not any(part in url_lower for part in video_parts)


def extract_x_username(url: str):
    match = re.search(r"(?:x\.com|twitter\.com)/([^/?#]+)", url, re.I)
    if not match:
        return None

    username = match.group(1).strip()
    blocked = {
        "i", "intent", "share", "home", "search", "explore",
        "notifications", "messages", "settings", "compose"
    }

    if username.lower() in blocked:
        return None

    return username


def is_x_profile(url: str) -> bool:
    url_lower = url.lower()

    if "x.com/" not in url_lower and "twitter.com/" not in url_lower:
        return False

    post_parts = [
        "/status/",
        "/statuses/",
        "/i/",
        "/intent/",
        "/share",
        "/search",
        "/hashtag/"
    ]

    return not any(part in url_lower for part in post_parts) and extract_x_username(url) is not None


def extract_threads_username(url: str):
    url = normalize_threads_url(url)
    match = re.search(r"threads\.net/@([^/?#]+)", url, re.I)
    if not match:
        return None

    return match.group(1).strip()


def is_threads_profile(url: str) -> bool:
    url_lower = url.lower()

    if "threads.net/@" not in url_lower:
        return False

    post_parts = [
        "/post/",
        "/t/",
    ]

    return not any(part in url_lower for part in post_parts) and extract_threads_username(url) is not None


def is_social_profile(url: str) -> bool:
    return (
        is_instagram_profile(url)
        or is_tiktok_profile(url)
        or is_x_profile(url)
        or is_threads_profile(url)
    )


def detect_platform(url: str) -> str:
    url_lower = url.lower()

    if "instagram.com" in url_lower:
        if "/reel/" in url_lower or "/reels/" in url_lower:
            return "Instagram Reels"
        if "/p/" in url_lower:
            return "Instagram Post"
        if "/stories/" in url_lower:
            return "Instagram Story"
        return "Instagram Profile"

    if "tiktok.com" in url_lower or "vm.tiktok.com" in url_lower:
        if is_tiktok_profile(url):
            return "TikTok Profile"
        if "/video/" in url_lower or "vm.tiktok.com" in url_lower:
            return "TikTok Video"
        return "TikTok"

    if "x.com" in url_lower or "twitter.com" in url_lower:
        if is_x_profile(url):
            return "X Profile"
        if "/status/" in url_lower or "/statuses/" in url_lower:
            return "X Post"
        return "X"

    if "threads.net" in url_lower or "threads.com" in url_lower:
        normalized_threads = normalize_threads_url(url)
        normalized_lower = normalized_threads.lower()

        if is_threads_profile(normalized_threads):
            return "Threads Profile"
        if "/post/" in normalized_lower or "/t/" in normalized_lower:
            return "Threads Post"
        return "Threads"

    if "youtube.com/shorts" in url_lower:
        return "YouTube Shorts"

    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"

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
    return Path(path).exists() and Path(path).is_file()


def build_video_caption(platform, url, thought, priority_label, status_label, reminder_label=None):
    reminder_line = ""

    if reminder_label:
        reminder_line = f"\n🔔 Reminder: {reminder_label}"

    return (
        f"🎬 {platform}\n\n"
        f"⚡ Priority: {priority_label}\n"
        f"📌 Status: {status_label}"
        f"{reminder_line}\n\n"
        f"🔗 Link:\n{url}\n\n"
        f"💭 Notes:\n{thought}"
    )


def build_profile_caption(url, thought, platform="Instagram Profile"):
    if platform == "TikTok Profile":
        username = extract_tiktok_username(url)
        clean_profile_url = clean_url(url)
        title = "🎵 TikTok Profile Reference"
    else:
        username = extract_instagram_username(url)
        clean_profile_url = normalize_instagram_url(url)
        title = "📸 Instagram Profile Reference"

    account_line = f"@{username}" if username else "Unknown"

    return (
        f"{title}\n\n"
        f"👤 Account:\n"
        f"{account_line}\n\n"
        f"🔗 Profile Link:\n"
        f"{clean_profile_url}\n\n"
        f"💭 Notes:\n"
        f"{thought}"
    )


def extract_profile_username(url, platform):
    if platform == "Instagram Profile":
        return extract_instagram_username(url)
    if platform == "TikTok Profile":
        return extract_tiktok_username(url)
    if platform == "X Profile":
        return extract_x_username(url)
    if platform == "Threads Profile":
        return extract_threads_username(url)
    return None


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================
# TELEGRAM MESSAGE HELPERS
# =========================

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


async def safe_edit_message(query, text, reply_markup=None):
    try:
        if query.message and query.message.photo:
            await query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup
            )
        else:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup
            )
    except Exception:
        try:
            await query.message.reply_text(
                text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"safe_edit_message failed: {type(e).__name__}: {repr(e)}")


# =========================
# MEDIA
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

            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": expires,
                "httpOnly": http_only,
                "secure": secure.upper() == "TRUE",
                "sameSite": "Lax"
            })

        logger.info(f"Загружено cookies для Playwright: {len(cookies)}")
        return cookies

    except Exception as e:
        logger.error(f"Ошибка чтения cookies.txt для Playwright: {type(e).__name__}: {repr(e)}")
        return []


def select_best_downloaded_media(video_id: str):
    """
    yt-dlp can download several files for X/Threads/Twitter posts.
    This chooses the best usable video file instead of assuming there is only one.
    """
    files = [
        p for p in DOWNLOAD_DIR.glob(f"{video_id}.*")
        if p.is_file() and p.stat().st_size > 0
    ]

    if not files:
        return None

    video_ext_priority = {
        ".mp4": 1,
        ".mov": 2,
        ".m4v": 3,
        ".webm": 4,
        ".mkv": 5,
    }

    video_files = [
        p for p in files
        if p.suffix.lower() in video_ext_priority
    ]

    if video_files:
        # Prefer mp4/mov first, then bigger file size.
        video_files.sort(
            key=lambda p: (
                video_ext_priority.get(p.suffix.lower(), 99),
                -p.stat().st_size
            )
        )
        return str(video_files[0])

    # If there is no obvious video file, return the biggest file as last resort.
    files.sort(key=lambda p: -p.stat().st_size)
    return str(files[0])


def download_video_sync(url: str):
    video_id = str(uuid.uuid4())
    output_template = str(DOWNLOAD_DIR / f"{video_id}.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,

        # Safer universal format for Instagram/TikTok/X/Threads.
        # We prefer normal MP4/H.264 up to 720p because Telegram handles it more reliably.
        "format": (
            "best[vcodec^=avc1][height<=720][ext=mp4]/"
            "best[vcodec^=h264][height<=720][ext=mp4]/"
            "best[height<=720][ext=mp4]/"
            "best[ext=mp4]/"
            "best"
        ),
        "format_sort": ["vcodec:h264", "ext:mp4", "res:720", "fps"],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": 48 * 1024 * 1024,
        "merge_output_format": "mp4",
        "socket_timeout": 25,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 2,
    }

    if Path(COOKIES_FILE).exists():
        logger.info("cookies.txt найден. Использую cookies для yt-dlp.")
        ydl_opts["cookiefile"] = str(COOKIES_FILE)
    else:
        logger.warning("cookies.txt не найден. Некоторые платформы могут не скачаться.")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    downloaded_path = select_best_downloaded_media(video_id)

    if not downloaded_path or not os.path.exists(downloaded_path):
        raise FileNotFoundError("Видео не было скачано или подходящий файл не найден.")

    return downloaded_path


async def download_video(url: str):
    return await asyncio.to_thread(download_video_sync, url)


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
            return "continue" in text.lower()
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

    for x, y in [(195, 515), (195, 535), (195, 555), (195, 575), (195, 595), (195, 615)]:
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


async def make_profile_screenshot(url: str):
    screenshot_id = str(uuid.uuid4())
    screenshot_path = str(DOWNLOAD_DIR / f"{screenshot_id}.png")

    cookies = load_netscape_cookies_for_playwright(str(COOKIES_FILE))
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

            await goto_instagram_page(page, url, "profile-first")

            did_continue = await click_continue_if_needed(page)

            if did_continue:
                await goto_instagram_page(page, url, "profile-after-continue")

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
                    await goto_instagram_page(page, url, "profile-final")
                    await close_instagram_popups(page)
                    await page.wait_for_timeout(2000)

            except Exception as e:
                logger.warning(f"Финальная проверка URL failed: {type(e).__name__}: {repr(e)}")

            await page.wait_for_timeout(4000)

            try:
                await page.mouse.wheel(0, 250)
                await page.wait_for_timeout(1000)
                await page.mouse.wheel(0, -250)
                await page.wait_for_timeout(1000)
            except Exception:
                pass

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


# Backward compatibility name
make_instagram_profile_screenshot = make_profile_screenshot


# =========================
# EXPORT
# =========================

def create_export_json():
    export_path = DOWNLOAD_DIR / "referens_database.json"

    with export_path.open("w", encoding="utf-8") as f:
        json.dump(load_database(), f, ensure_ascii=False, indent=2)

    return str(export_path)


def create_export_csv():
    data = load_database()
    export_path = DOWNLOAD_DIR / "referens_database.csv"

    fields = [
        "id",
        "created_at",
        "type",
        "topic",
        "platform",
        "username",
        "url",
        "notes",
        "priority",
        "status",
        "reminder",
        "message_id",
        "chat_id"
    ]

    with export_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for item in data:
            writer.writerow({
                "id": item.get("id", ""),
                "created_at": item.get("created_at", ""),
                "type": item.get("type", ""),
                "topic": item.get("topic", ""),
                "platform": item.get("platform", ""),
                "username": item.get("username", ""),
                "url": item.get("url", ""),
                "notes": item.get("notes", ""),
                "priority": item.get("priority_label", item.get("priority", "")),
                "status": item.get("status_label", item.get("status", "")),
                "reminder": item.get("reminder_label", ""),
                "message_id": item.get("message_id", ""),
                "chat_id": item.get("chat_id", "")
            })

    return str(export_path)
