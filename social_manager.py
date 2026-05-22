import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from config import ANALYTICS_FILE
from social_cards import create_social_card, k_format, platform_label
from pdf_reports import create_social_pdf
from social_collectors import collect_profile_stats, collect_recent_stats, normalize_platform, platform_url


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
    Path(ANALYTICS_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_username(platform, text):
    text = text.strip()
    platform = normalize_platform(platform)
    if text.startswith("@"):
        username = text[1:].strip().strip("/")
        return username, platform_url(platform, username)
    patterns = {
        "instagram": r"instagram\.com/([^/?#]+)/?",
        "tiktok": r"tiktok\.com/@([^/?#]+)",
        "x": r"(?:x\.com|twitter\.com)/([^/?#]+)",
        "threads": r"(?:threads\.net|threads\.com)/@([^/?#]+)",
    }
    m = re.search(patterns.get(platform, r"$^"), text, re.I)
    if m:
        return m.group(1).strip(), text
    username = text.lstrip("@").strip("/")
    return username, platform_url(platform, username)


def add_account(owner_id, platform, username, url):
    data = _load()
    platform = normalize_platform(platform)
    username = username.lstrip("@").strip()
    for acc in data["accounts"]:
        if str(acc.get("owner_id")) == str(owner_id) and acc.get("platform") == platform and acc.get("username", "").lower() == username.lower():
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
    accounts = [a for a in _load()["accounts"] if str(a.get("owner_id")) == str(owner_id)]
    if platform:
        accounts = [a for a in accounts if a.get("platform") == normalize_platform(platform)]
    return accounts


def get_account(owner_id, account_id):
    return next((a for a in list_accounts(owner_id) if a.get("id") == account_id), None)


def delete_account(owner_id, account_id):
    data = _load()
    data["accounts"] = [a for a in data["accounts"] if not (str(a.get("owner_id")) == str(owner_id) and a.get("id") == account_id)]
    _save(data)


def save_snapshot(owner_id, account_id, stats):
    data = _load()
    snap = {
        "id": str(uuid.uuid4()),
        "owner_id": int(owner_id),
        "account_id": account_id,
        "created_at": current_timestamp(),
        "data": stats,
    }
    data["snapshots"].append(snap)
    _save(data)
    return snap


def get_last_snapshot(owner_id, account_id):
    snaps = [s for s in _load()["snapshots"] if str(s.get("owner_id")) == str(owner_id) and s.get("account_id") == account_id]
    return snaps[-1] if snaps else None


def latest_stats(owner_id, account_id):
    snap = get_last_snapshot(owner_id, account_id)
    return snap.get("data") if snap else {}


def count_by_platform(owner_id):
    counts = {"instagram": 0, "tiktok": 0, "x": 0, "threads": 0}
    for acc in list_accounts(owner_id):
        if acc.get("platform") in counts:
            counts[acc.get("platform")] += 1
    return counts


async def collect_stats(account, count=0):
    if int(count or 0) <= 0:
        return await collect_profile_stats(account)
    return await collect_recent_stats(account, count=int(count))


def social_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Быстрая статистика", callback_data="social_fast")],
        [InlineKeyboardButton("📋 Все аккаунты", callback_data="social_accounts_all")],
        [InlineKeyboardButton("➕ Добавить аккаунт", callback_data="social_add")],
        [InlineKeyboardButton("📄 PDF отчёт", callback_data="social_pdf_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")],
    ])


def platform_keyboard(prefix="social_add_platform"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Instagram", callback_data=f"{prefix}:instagram"), InlineKeyboardButton("🎵 TikTok", callback_data=f"{prefix}:tiktok")],
        [InlineKeyboardButton("𝕏 X", callback_data=f"{prefix}:x"), InlineKeyboardButton("🧵 Threads", callback_data=f"{prefix}:threads")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="social_main")]
    ])


def account_keyboard(account_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Общая стата", callback_data=f"social_acc_summary:{account_id}"), InlineKeyboardButton("🎬 Последнее", callback_data=f"social_acc_stats:1:{account_id}")],
        [InlineKeyboardButton("🎬 Последние 3", callback_data=f"social_acc_stats:3:{account_id}")],
        [InlineKeyboardButton("📄 PDF", callback_data=f"social_acc_pdf:{account_id}"), InlineKeyboardButton("🔄 Обновить", callback_data=f"social_acc_refresh:{account_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"social_acc_delete:{account_id}")],
        [InlineKeyboardButton("⬅️ Все аккаунты", callback_data="social_accounts_all")]
    ])


def all_accounts_keyboard(owner_id):
    counts = count_by_platform(owner_id)
    rows = [
        [InlineKeyboardButton(f"📸 Instagram — {counts['instagram']}   🎵 TikTok — {counts['tiktok']}", callback_data="social_counts_info")],
        [InlineKeyboardButton(f"𝕏 X — {counts['x']}   🧵 Threads — {counts['threads']}", callback_data="social_counts_info")],
    ]
    accounts = list_accounts(owner_id)
    if not accounts:
        rows.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="social_add")])
    else:
        for acc in accounts:
            stats = latest_stats(owner_id, acc["id"])
            suffix = ""
            if stats.get("followers") is not None:
                suffix += f" · {k_format(stats.get('followers'))} followers"
            if stats.get("total_likes") is not None:
                suffix += f" · {k_format(stats.get('total_likes'))} likes"
            rows.append([InlineKeyboardButton(f"{platform_label(acc.get('platform'))} @{acc.get('username')}{suffix}", callback_data=f"social_account:{acc.get('id')}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="social_main")])
    return InlineKeyboardMarkup(rows)


def profile_summary_text(account, stats, title="✅ Аккаунт добавлен"):
    lines = [
        title, "",
        f"{platform_label(account.get('platform'))} @{account.get('username')}", "",
        f"👥 Followers: {k_format(stats.get('followers'))}",
        f"👤 Following: {k_format(stats.get('following'))}",
        f"📦 Posts/Videos: {k_format(stats.get('total_posts'))}",
        f"❤️ Total likes: {k_format(stats.get('total_likes'))}",
        f"👁 Total views: {k_format(stats.get('total_views'))}",
        f"📊 Avg ER: {stats.get('avg_er', 0)}%",
        f"Status: {stats.get('status')}",
        f"Source: {stats.get('source') or 'unknown'}",
    ]
    if stats.get("note"):
        lines += ["", f"Note: {stats.get('note')}"]
    else:
        lines += ["", "Что хочешь посмотреть?"]
    return "\n".join(lines)


def report_text(account, stats, count=3):
    lines = [
        f"📊 {platform_label(account.get('platform'))} @{account.get('username')}",
        "🎬 Последнее видео/пост" if count == 1 else f"🎬 Последние {count} видео/поста",
        f"Source: {stats.get('source') or 'unknown'}",
        ""
    ]
    if stats.get("followers") is not None:
        lines.append(f"👥 Followers: {k_format(stats.get('followers'))}")
    if stats.get("total_likes") is not None:
        lines.append(f"❤️ Total likes: {k_format(stats.get('total_likes'))}")
    if stats.get("total_posts") is not None:
        lines.append(f"📦 Posts/Videos: {k_format(stats.get('total_posts'))}")
    if lines[-1] != "":
        lines.append("")
    if not stats.get("videos"):
        lines.append("⚠️ Детальные данные по последним постам недоступны.")
        if stats.get("note"):
            lines.append(f"Причина: {stats.get('note')}")
        return "\n".join(lines)
    for video in stats["videos"][:count]:
        lines += [
            f"#{video.get('rank')} — {video.get('posted_ago', 'unknown')}",
            f"👁 Просмотры: {k_format(video.get('views'))}",
            f"❤️ Лайки: {k_format(video.get('likes'))}",
            f"💬 Комментарии: {k_format(video.get('comments'))}",
            f"🔁 Поделились/репосты: {k_format(video.get('shares'))}",
            f"📊 ER: {video.get('er', 0)}%",
            f"🚀 Потенциал: {video.get('potential', 'Low')}",
            f"🔗 {video.get('url', '')}",
            ""
        ]
    return "\n".join(lines).strip()


async def social_cmd(update, context):
    await update.message.reply_text("📊 Соцсети\n\nБыстрый доступ к аккаунтам, статистике и PDF отчётам.", reply_markup=social_main_keyboard())


async def handle_social_text_mode(update, context, text):
    if context.user_data.get("mode") != "awaiting_social_username":
        return False
    user_id = update.effective_user.id
    platform = context.user_data.get("social_platform")
    username, url = extract_username(platform, text)
    account = add_account(user_id, platform, username, url)

    await update.message.reply_text("⏳ Добавляю аккаунт и собираю быструю общую статистику...")
    stats = await collect_stats(account, 0)
    save_snapshot(user_id, account["id"], stats)

    card = create_social_card(account, stats, 0)
    with open(card, "rb") as photo:
        await update.message.reply_photo(photo=photo, caption=profile_summary_text(account, stats), reply_markup=account_keyboard(account["id"]))

    context.user_data.pop("mode", None)
    context.user_data.pop("social_platform", None)
    return True


async def social_callback(update, context, safe_edit_message):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "social_main":
        await safe_edit_message(query, "📊 Соцсети\n\nЧто хочешь сделать?", reply_markup=social_main_keyboard())
        return

    if data in {"social_fast", "social_accounts_all"}:
        await safe_edit_message(query, "📋 Все аккаунты\n\nСверху — количество аккаунтов по платформам. Ниже — все аккаунты сразу:", reply_markup=all_accounts_keyboard(user_id))
        return

    if data == "social_counts_info":
        await query.answer("Это сводка по количеству аккаунтов.", show_alert=False)
        return

    if data == "social_add":
        await safe_edit_message(query, "➕ Добавить аккаунт\n\nВыбери платформу:", reply_markup=platform_keyboard())
        return

    if data.startswith("social_add_platform:"):
        platform = data.split(":", 1)[1]
        context.user_data["mode"] = "awaiting_social_username"
        context.user_data["social_platform"] = platform
        await safe_edit_message(query, f"{platform_label(platform)}\n\nОтправь username или ссылку на аккаунт.\n\nПример:\n@username")
        return

    if data.startswith("social_account:"):
        account_id = data.split(":", 1)[1]
        acc = get_account(user_id, account_id)
        if not acc:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return
        stats = latest_stats(user_id, account_id)
        if not stats:
            await safe_edit_message(query, "⏳ Собираю быструю статистику...")
            stats = await collect_stats(acc, 0)
            save_snapshot(user_id, account_id, stats)
        await safe_edit_message(query, profile_summary_text(acc, stats, title="📊 Общая статистика"), reply_markup=account_keyboard(account_id))
        return

    if data.startswith("social_acc_summary:"):
        account_id = data.split(":", 1)[1]
        acc = get_account(user_id, account_id)
        if not acc:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return
        stats = latest_stats(user_id, account_id)
        if not stats:
            await safe_edit_message(query, "⏳ Собираю быструю статистику...")
            stats = await collect_stats(acc, 0)
            save_snapshot(user_id, account_id, stats)
        await safe_edit_message(query, profile_summary_text(acc, stats, title="📊 Общая статистика"), reply_markup=account_keyboard(account_id))
        return

    if data.startswith("social_acc_refresh:"):
        account_id = data.split(":", 1)[1]
        acc = get_account(user_id, account_id)
        if not acc:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return
        await safe_edit_message(query, "⏳ Обновляю быструю общую статистику...")
        stats = await collect_stats(acc, 0)
        save_snapshot(user_id, account_id, stats)
        await safe_edit_message(query, profile_summary_text(acc, stats, title="✅ Статистика обновлена"), reply_markup=account_keyboard(account_id))
        return

    if data.startswith("social_acc_stats:"):
        _, count, account_id = data.split(":", 2)
        count = int(count)
        acc = get_account(user_id, account_id)
        if not acc:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return
        await safe_edit_message(query, "⏳ Собираю статистику по последним постам...")
        stats = await collect_stats(acc, count)
        save_snapshot(user_id, account_id, stats)
        card = create_social_card(acc, stats, count)
        caption = report_text(acc, stats, count)
        try:
            await query.message.delete()
        except Exception:
            pass
        with open(card, "rb") as photo:
            await query.message.chat.send_photo(photo=photo, caption=caption[:1000], reply_markup=account_keyboard(account_id))
        if len(caption) > 1000:
            await query.message.chat.send_message(caption[1000:])
        return

    if data.startswith("social_acc_pdf:"):
        account_id = data.split(":", 1)[1]
        acc = get_account(user_id, account_id)
        if not acc:
            await safe_edit_message(query, "Аккаунт не найден.", reply_markup=social_main_keyboard())
            return
        stats = latest_stats(user_id, account_id) or await collect_stats(acc, 0)
        save_snapshot(user_id, account_id, stats)
        pdf = create_social_pdf([acc], {acc["id"]: stats}, title=f"Social Report @{acc.get('username')}")
        with open(pdf, "rb") as f:
            await query.message.reply_document(document=InputFile(f, filename=Path(pdf).name), caption="📄 PDF отчёт готов.")
        return

    if data == "social_pdf_all":
        accounts = list_accounts(user_id)
        if not accounts:
            await safe_edit_message(query, "Аккаунтов пока нет.", reply_markup=social_main_keyboard())
            return
        stats_by = {}
        for acc in accounts:
            st = latest_stats(user_id, acc["id"])
            if not st:
                st = await collect_stats(acc, 0)
                save_snapshot(user_id, acc["id"], st)
            stats_by[acc["id"]] = st
        pdf = create_social_pdf(accounts, stats_by, title="Social Accounts Report")
        with open(pdf, "rb") as f:
            await query.message.reply_document(document=InputFile(f, filename=Path(pdf).name), caption="📄 PDF отчёт готов.")
        return

    if data.startswith("social_acc_delete:"):
        account_id = data.split(":", 1)[1]
        delete_account(user_id, account_id)
        await safe_edit_message(query, "🗑 Аккаунт удалён.", reply_markup=all_accounts_keyboard(user_id))
        return
