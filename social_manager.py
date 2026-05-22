import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from config import ANALYTICS_FILE
from social_cards import create_social_card, k_format, platform_label
from pdf_reports import create_social_pdf


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load():
    path = Path(ANALYTICS_FILE)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
    else:
        data = {}

    data.setdefault("accounts", [])
    data.setdefault("snapshots", [])

    return data


def _save(data):
    Path(ANALYTICS_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def norm_platform(platform):
    platform = (platform or "").lower().strip()

    if platform in {"ig", "insta", "instagram"}:
        return "instagram"

    if platform in {"tt", "tiktok"}:
        return "tiktok"

    if platform in {"x", "twitter"}:
        return "x"

    return platform


def build_account_url(platform, username):
    platform = norm_platform(platform)
    username = username.lstrip("@")

    if platform == "instagram":
        return f"https://www.instagram.com/{username}/"

    if platform == "tiktok":
        return f"https://www.tiktok.com/@{username}"

    if platform == "x":
        return f"https://x.com/{username}"

    return username


def extract_username(platform, text):
    text = text.strip()
    platform = norm_platform(platform)

    if text.startswith("@"):
        username = text[1:].strip()
        return username, build_account_url(platform, username)

    patterns = {
        "instagram": r"instagram\.com/([^/?#]+)/?",
        "tiktok": r"tiktok\.com/@([^/?#]+)",
        "x": r"(?:x\.com|twitter\.com)/([^/?#]+)"
    }

    pattern = patterns.get(platform)
    if pattern:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1), text

    username = text.strip().lstrip("@").strip("/")
    return username, build_account_url(platform, username)


def add_account(owner_id, platform, username, url):
    data = _load()

    platform = norm_platform(platform)
    username = username.lstrip("@")

    for acc in data["accounts"]:
        if (
            str(acc.get("owner_id")) == str(owner_id)
            and acc.get("platform") == platform
            and acc.get("username", "").lower() == username.lower()
        ):
            acc["url"] = url
            acc["updated_at"] = current_timestamp()
            _save(data)
            return acc

    acc = {
        "id": str(uuid.uuid4()),
        "owner_id": int(owner_id),
        "platform": platform,
        "username": username,
        "url": url,
        "added_at": current_timestamp(),
        "updated_at": current_timestamp(),
    }

    data["accounts"].append(acc)
    _save(data)

    return acc


def list_accounts(owner_id, platform=None):
    accounts = [
        acc for acc in _load()["accounts"]
        if str(acc.get("owner_id")) == str(owner_id)
    ]

    if platform:
        accounts = [
            acc for acc in accounts
            if acc.get("platform") == norm_platform(platform)
        ]

    return accounts


def get_account(owner_id, account_id):
    for acc in list_accounts(owner_id):
        if acc.get("id") == account_id:
            return acc

    return None


def delete_account(owner_id, account_id):
    data = _load()

    data["accounts"] = [
        acc for acc in data["accounts"]
        if not (
            str(acc.get("owner_id")) == str(owner_id)
            and acc.get("id") == account_id
        )
    ]

    _save(data)


def save_snapshot(owner_id, account_id, stats):
    data = _load()

    snap = {
        "id": str(uuid.uuid4()),
        "owner_id": int(owner_id),
        "account_id": account_id,
        "created_at": current_timestamp(),
        "data": stats
    }

    data["snapshots"].append(snap)
    _save(data)

    return snap


def get_last_snapshot(owner_id, account_id):
    snapshots = [
        snap for snap in _load()["snapshots"]
        if str(snap.get("owner_id")) == str(owner_id)
        and snap.get("account_id") == account_id
    ]

    return snapshots[-1] if snapshots else None


def calc_er(views, likes, comments, shares):
    views = float(views or 0)

    if views <= 0:
        return 0

    return round(
        ((float(likes or 0) + float(comments or 0) + float(shares or 0)) / views) * 100,
        2
    )


def potential(video):
    er = calc_er(
        video.get("views"),
        video.get("likes"),
        video.get("comments"),
        video.get("shares")
    )

    age_hours = float(video.get("age_hours") or 999)

    score = 0
    reasons = []

    if age_hours <= 6:
        score += 3
        reasons.append("fresh")
    elif age_hours <= 24:
        score += 2
        reasons.append("new")

    if er >= 10:
        score += 3
        reasons.append("strong ER")
    elif er >= 5:
        score += 2
        reasons.append("good ER")

    views = float(video.get("views") or 0)
    shares = float(video.get("shares") or 0)

    if views > 0 and shares / views * 100 >= 0.5:
        score += 2
        reasons.append("shares signal")

    if score >= 5:
        return "High", ", ".join(reasons[:3]) or "strong signals"

    if score >= 2:
        return "Medium", ", ".join(reasons[:3]) or "some good signals"

    return "Low", ", ".join(reasons[:3]) or "weak signals"


async def collect_stats(account, count=3):
    count = max(1, min(int(count or 3), 3))

    data = {
        "platform": account.get("platform"),
        "username": account.get("username"),
        "url": account.get("url"),
        "total_views": 0,
        "total_likes": 0,
        "total_comments": 0,
        "total_shares": 0,
        "avg_er": 0,
        "videos": [],
        "status": "unavailable",
        "note": "Public data unavailable. Platform may require cookies."
    }

    try:
        def extract():
            with yt_dlp.YoutubeDL({
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "skip_download": True,
                "playlistend": count,
            }) as ydl:
                return ydl.extract_info(account.get("url"), download=False)

        info = await asyncio.to_thread(extract)

        entries = info.get("entries") if isinstance(info, dict) else None
        source = entries[:count] if entries else [info]

        for i, entry in enumerate(source[:count], 1):
            if not entry:
                continue

            views = entry.get("view_count") or 0
            likes = entry.get("like_count") or 0
            comments = entry.get("comment_count") or 0
            shares = entry.get("repost_count") or entry.get("share_count") or 0

            timestamp = entry.get("timestamp")
            age_hours = 999
            posted_ago = "unknown"

            if timestamp:
                age_hours = round((time.time() - float(timestamp)) / 3600, 1)
                posted_ago = f"{age_hours:g}h ago" if age_hours < 24 else f"{round(age_hours / 24, 1):g}d ago"

            er = calc_er(views, likes, comments, shares)
            growth, reason = potential({
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "age_hours": age_hours
            })

            if views or likes or comments or shares:
                data["videos"].append({
                    "rank": i,
                    "url": entry.get("webpage_url") or entry.get("url") or account.get("url"),
                    "posted_ago": posted_ago,
                    "age_hours": age_hours,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "er": er,
                    "potential": growth,
                    "potential_reason": reason,
                })

    except Exception as e:
        data["note"] = f"{type(e).__name__}: {e}"

    data["total_views"] = sum(int(v.get("views") or 0) for v in data["videos"])
    data["total_likes"] = sum(int(v.get("likes") or 0) for v in data["videos"])
    data["total_comments"] = sum(int(v.get("comments") or 0) for v in data["videos"])
    data["total_shares"] = sum(int(v.get("shares") or 0) for v in data["videos"])

    if data["videos"]:
        data["avg_er"] = round(
            sum(float(v.get("er") or 0) for v in data["videos"]) / len(data["videos"]),
            2
        )

    data["status"] = "ok" if data["videos"] else "unavailable"

    return data


def social_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить аккаунт", callback_data="social_add")],
        [InlineKeyboardButton("📋 Мои аккаунты", callback_data="social_accounts")],
        [InlineKeyboardButton("📈 Быстрый отчёт", callback_data="social_quick")],
        [InlineKeyboardButton("📄 PDF отчёт", callback_data="social_pdf")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ])


def platform_keyboard(prefix="social_add_platform"):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Instagram", callback_data=f"{prefix}:instagram"),
            InlineKeyboardButton("🎵 TikTok", callback_data=f"{prefix}:tiktok"),
            InlineKeyboardButton("𝕏 X", callback_data=f"{prefix}:x")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="social_main")]
    ])


def account_keyboard(account_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Общая стата", callback_data=f"social_acc_summary:{account_id}"),
            InlineKeyboardButton("🎬 Последнее", callback_data=f"social_acc_stats:1:{account_id}")
        ],
        [InlineKeyboardButton("🎬 Последние 3", callback_data=f"social_acc_stats:3:{account_id}")],
        [
            InlineKeyboardButton("📄 PDF", callback_data=f"social_acc_pdf:{account_id}"),
            InlineKeyboardButton("🔄 Пересобрать", callback_data=f"social_acc_refresh:{account_id}")
        ],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"social_acc_delete:{account_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="social_accounts")]
    ])


def platform_counts_keyboard(user_id):
    counts = {"instagram": 0, "tiktok": 0, "x": 0}

    for account in list_accounts(user_id):
        platform = account.get("platform")
        if platform in counts:
            counts[platform] += 1

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📸 Instagram — {counts['instagram']}", callback_data="social_accounts_platform:instagram")],
        [InlineKeyboardButton(f"🎵 TikTok — {counts['tiktok']}", callback_data="social_accounts_platform:tiktok")],
        [InlineKeyboardButton(f"𝕏 X — {counts['x']}", callback_data="social_accounts_platform:x")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="social_main")]
    ])


def accounts_list_keyboard(user_id, platform):
    rows = []

    for account in list_accounts(user_id, platform):
        rows.append([
            InlineKeyboardButton(
                f"@{account.get('username')}",
                callback_data=f"social_account:{account.get('id')}"
            )
        ])

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="social_accounts")])

    return InlineKeyboardMarkup(rows)


def report_text(account, stats, count=3):
    lines = [
        f"📊 {platform_label(account.get('platform'))} @{account.get('username')}",
        "🎬 Последнее видео" if count == 1 else f"🎬 Последние {count} видео",
        ""
    ]

    if not stats.get("videos"):
        return "\n".join(lines + [
            "⚠️ Публичные данные недоступны.",
            f"Причина: {stats.get('note', '')}"
        ])

    for video in stats["videos"][:count]:
        lines += [
            f"#{video.get('rank')} — {video.get('posted_ago', 'unknown')}",
            f"👁 Просмотры: {k_format(video.get('views'))}",
            f"❤️ Лайки: {k_format(video.get('likes'))}",
            f"💬 Комментарии: {k_format(video.get('comments'))}",
            f"🔁 Поделились: {k_format(video.get('shares'))}",
            f"📊 ER: {video.get('er', 0)}%",
            f"🚀 Потенциал: {video.get('potential', 'Low')}",
            f"Причина: {video.get('potential_reason', '')}",
            f"🔗 {video.get('url', '')}",
            ""
        ]

    return "\n".join(lines).strip()


async def social_cmd(update, context):
    await update.message.reply_text(
        "📊 Соцсети\n\nДобавляй аккаунты и смотри статистику по последним видео.",
        reply_markup=social_main_keyboard()
    )


async def handle_social_text_mode(update, context, text):
    if context.user_data.get("mode") != "awaiting_social_username":
        return False

    user_id = update.effective_user.id
    platform = context.user_data.get("social_platform")

    username, url = extract_username(platform, text)
    account = add_account(user_id, platform, username, url)

    await update.message.reply_text("⏳ Проверяю аккаунт и собираю первую статистику...")

    stats = await collect_stats(account, 3)
    save_snapshot(user_id, account["id"], stats)

    card = create_social_card(account, stats, 3)
    caption = report_text(account, stats, 3)

    with open(card, "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=caption[:1000],
            reply_markup=account_keyboard(account["id"])
        )

    if len(caption) > 1000:
        await update.message.reply_text(caption[1000:])

    context.user_data.pop("mode", None)
    context.user_data.pop("social_platform", None)

    return True


async def social_callback(update, context, safe_edit_message):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "social_main":
        await safe_edit_message(
            query,
            "📊 Соцсети\n\nЧто хочешь сделать?",
            reply_markup=social_main_keyboard()
        )
        return

    if data == "social_add":
        await safe_edit_message(
            query,
            "➕ Добавить аккаунт\n\nВыбери платформу:",
            reply_markup=platform_keyboard()
        )
        return

    if data.startswith("social_add_platform:"):
        platform = data.split(":", 1)[1]
        context.user_data["mode"] = "awaiting_social_username"
        context.user_data["social_platform"] = platform

        await safe_edit_message(
            query,
            f"{platform_label(platform)}\n\nОтправь username или ссылку на аккаунт.\n\nПример:\n@username"
        )
        return

    if data == "social_accounts":
        await safe_edit_message(
            query,
            "📋 Мои аккаунты\n\nВыбери платформу:",
            reply_markup=platform_counts_keyboard(user_id)
        )
        return

    if data.startswith("social_accounts_platform:"):
        platform = data.split(":", 1)[1]

        await safe_edit_message(
            query,
            f"{platform_label(platform)} аккаунты\n\nВыбери аккаунт:",
            reply_markup=accounts_list_keyboard(user_id, platform)
        )
        return

    if data.startswith("social_account:"):
        account_id = data.split(":", 1)[1]
        account = get_account(user_id, account_id)

        if not account:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return

        snapshot = get_last_snapshot(user_id, account_id)
        stats = snapshot.get("data") if snapshot else {}

        await safe_edit_message(
            query,
            f"{platform_label(account.get('platform'))} @{account.get('username')}\n\n"
            f"👁 Views: {k_format(stats.get('total_views', 0))}\n"
            f"❤️ Likes: {k_format(stats.get('total_likes', 0))}\n"
            f"📊 Avg ER: {stats.get('avg_er', 0)}%\n"
            f"⏱ Last update: {snapshot.get('created_at') if snapshot else 'never'}",
            reply_markup=account_keyboard(account_id)
        )
        return

    if data.startswith("social_acc_stats:"):
        _, count, account_id = data.split(":", 2)
        count = int(count)
        account = get_account(user_id, account_id)

        if not account:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return

        await safe_edit_message(query, "⏳ Собираю статистику...")

        stats = await collect_stats(account, count)
        save_snapshot(user_id, account_id, stats)

        card = create_social_card(account, stats, count)
        caption = report_text(account, stats, count)

        try:
            await query.message.delete()
        except Exception:
            pass

        with open(card, "rb") as photo:
            await query.message.chat.send_photo(
                photo=photo,
                caption=caption[:1000],
                reply_markup=account_keyboard(account_id)
            )

        if len(caption) > 1000:
            await query.message.chat.send_message(caption[1000:])

        return

    if data.startswith("social_acc_summary:"):
        account_id = data.split(":", 1)[1]
        account = get_account(user_id, account_id)

        if not account:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return

        snapshot = get_last_snapshot(user_id, account_id)
        stats = snapshot.get("data") if snapshot else await collect_stats(account, 3)

        if not snapshot:
            save_snapshot(user_id, account_id, stats)

        await safe_edit_message(
            query,
            f"📊 Общая статистика аккаунта\n\n"
            f"{platform_label(account.get('platform'))} @{account.get('username')}\n\n"
            f"👁 Total views: {k_format(stats.get('total_views'))}\n"
            f"❤️ Total likes: {k_format(stats.get('total_likes'))}\n"
            f"💬 Total comments: {k_format(stats.get('total_comments'))}\n"
            f"🔁 Total shares: {k_format(stats.get('total_shares'))}\n"
            f"📊 Avg ER: {stats.get('avg_er', 0)}%\n"
            f"🎬 Videos checked: {len(stats.get('videos', []))}",
            reply_markup=account_keyboard(account_id)
        )
        return

    if data.startswith("social_acc_refresh:"):
        account_id = data.split(":", 1)[1]
        account = get_account(user_id, account_id)

        if not account:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return

        await safe_edit_message(query, "⏳ Пересобираю статистику...")

        stats = await collect_stats(account, 3)
        save_snapshot(user_id, account_id, stats)

        await safe_edit_message(
            query,
            "✅ Статистика пересобрана.",
            reply_markup=account_keyboard(account_id)
        )
        return

    if data.startswith("social_acc_pdf:"):
        account_id = data.split(":", 1)[1]
        account = get_account(user_id, account_id)

        if not account:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return

        await safe_edit_message(query, "⏳ Генерирую PDF...")

        stats = await collect_stats(account, 3)
        save_snapshot(user_id, account_id, stats)

        pdf = create_social_pdf(
            [account],
            {account["id"]: stats},
            title=f"Social Report @{account.get('username')}"
        )

        with open(pdf, "rb") as file:
            await query.message.reply_document(
                document=InputFile(file, filename=Path(pdf).name),
                caption="📄 PDF отчёт готов."
            )

        return

    if data.startswith("social_acc_delete:"):
        account_id = data.split(":", 1)[1]
        delete_account(user_id, account_id)

        await safe_edit_message(
            query,
            "🗑 Аккаунт удалён.",
            reply_markup=social_main_keyboard()
        )
        return

    if data in {"social_quick", "social_pdf"}:
        await safe_edit_message(
            query,
            "Выбери платформу:",
            reply_markup=platform_keyboard(f"{data}_platform")
        )
        return

    if data.startswith("social_quick_platform:") or data.startswith("social_pdf_platform:"):
        platform = data.split(":", 1)[1]
        accounts = list_accounts(user_id, platform)

        if not accounts:
            await safe_edit_message(query, "Аккаунтов нет.", reply_markup=social_main_keyboard())
            return

        await safe_edit_message(query, "⏳ Собираю отчёт...")

        stats_by_account = {}

        for account in accounts[:10]:
            stats = await collect_stats(account, 3)
            save_snapshot(user_id, account["id"], stats)
            stats_by_account[account["id"]] = stats

        pdf = create_social_pdf(
            accounts[:10],
            stats_by_account,
            title=f"{platform_label(platform)} Report"
        )

        with open(pdf, "rb") as file:
            await query.message.reply_document(
                document=InputFile(file, filename=Path(pdf).name),
                caption="📄 PDF отчёт готов."
            )

        return
