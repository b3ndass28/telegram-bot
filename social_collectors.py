import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from html import unescape

import requests
from bs4 import BeautifulSoup

try:
    from instagrapi import Client as InstaClient
except Exception:
    InstaClient = None

from config import COOKIES_FILE


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_platform(platform):
    platform = (platform or "").lower().strip()
    if platform in {"ig", "insta", "instagram"}:
        return "instagram"
    if platform in {"tt", "tiktok"}:
        return "tiktok"
    if platform in {"x", "twitter"}:
        return "x"
    if platform in {"threads", "thread"}:
        return "threads"
    return platform


def parse_count(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().replace(",", "").replace(" ", "")

    multiplier = 1
    if text.lower().endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.lower().endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.lower().endswith("b"):
        multiplier = 1_000_000_000
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except Exception:
        return None


def calc_er(views, likes, comments, shares):
    views = float(views or 0)
    if views <= 0:
        return 0
    return round(((float(likes or 0) + float(comments or 0) + float(shares or 0)) / views) * 100, 2)


def growth_potential(video):
    views = int(video.get("views") or 0)
    likes = int(video.get("likes") or 0)
    comments = int(video.get("comments") or 0)
    shares = int(video.get("shares") or 0)
    age_hours = float(video.get("age_hours") or 999)
    er = calc_er(views, likes, comments, shares)

    score = 0
    reasons = []

    if age_hours <= 6:
        score += 3
        reasons.append("fresh")
    elif age_hours <= 24:
        score += 2
        reasons.append("new")
    elif age_hours <= 72:
        score += 1
        reasons.append("recent")

    if er >= 10:
        score += 3
        reasons.append("strong ER")
    elif er >= 5:
        score += 2
        reasons.append("good ER")
    elif er >= 2:
        score += 1
        reasons.append("some ER")

    if views > 0:
        share_rate = shares / views * 100
        comment_rate = comments / views * 100

        if share_rate >= 1:
            score += 2
            reasons.append("strong shares")
        elif share_rate >= 0.3:
            score += 1
            reasons.append("some shares")

        if comment_rate >= 0.5:
            score += 1
            reasons.append("comments active")

    if score >= 6:
        return "High", ", ".join(reasons[:3]) or "strong signals"

    if score >= 3:
        return "Medium", ", ".join(reasons[:3]) or "mixed signals"

    return "Low", ", ".join(reasons[:3]) or "weak signals"


def empty_stats(account, note="Public data unavailable."):
    return {
        "platform": normalize_platform(account.get("platform")),
        "username": account.get("username"),
        "url": account.get("url"),
        "followers": None,
        "following": None,
        "total_posts": None,
        "profile_pic_url": None,
        "total_views": 0,
        "total_likes": 0,
        "total_comments": 0,
        "total_shares": 0,
        "avg_er": 0,
        "videos": [],
        "status": "unavailable",
        "source": None,
        "note": note,
        "collected_at": current_timestamp(),
    }


def finalize_stats(stats):
    videos = stats.get("videos", [])

    for v in videos:
        v["views"] = int(v.get("views") or 0)
        v["likes"] = int(v.get("likes") or 0)
        v["comments"] = int(v.get("comments") or 0)
        v["shares"] = int(v.get("shares") or 0)
        v["er"] = calc_er(v.get("views"), v.get("likes"), v.get("comments"), v.get("shares"))
        potential, reason = growth_potential(v)
        v["potential"] = potential
        v["potential_reason"] = reason

    stats["total_views"] = sum(int(v.get("views") or 0) for v in videos)
    stats["total_likes"] = sum(int(v.get("likes") or 0) for v in videos)
    stats["total_comments"] = sum(int(v.get("comments") or 0) for v in videos)
    stats["total_shares"] = sum(int(v.get("shares") or 0) for v in videos)
    stats["avg_er"] = round(sum(float(v.get("er") or 0) for v in videos) / len(videos), 2) if videos else 0
    stats["status"] = "ok" if videos or stats.get("followers") is not None else "unavailable"
    return stats


def read_netscape_cookies(path=COOKIES_FILE):
    cookies = {}
    path = Path(path)

    if not path.exists():
        return cookies

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
        elif line.startswith("#"):
            continue

        parts = line.split("\t")

        if len(parts) >= 7:
            domain = parts[0].strip()
            name = parts[5].strip()
            value = parts[6].strip()
            if name:
                cookies[name] = {"value": value, "domain": domain}
            continue

        if "=" in line:
            name, value = line.split("=", 1)
            cookies[name.strip()] = {"value": value.strip(), "domain": ""}

    return cookies


def cookie_value(name):
    item = read_netscape_cookies().get(name)
    if not item:
        return None
    return item.get("value")


def session_with_cookies():
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for name, item in read_netscape_cookies().items():
        try:
            session.cookies.set(name, item.get("value"), domain=item.get("domain") or None)
        except Exception:
            try:
                session.cookies.set(name, item.get("value"))
            except Exception:
                pass

    return session


def ago_from_timestamp(ts):
    try:
        ts = float(ts)
    except Exception:
        return "unknown", 999

    age_hours = round((time.time() - ts) / 3600, 1)

    if age_hours < 24:
        return f"{age_hours:g}h ago", age_hours

    return f"{round(age_hours / 24, 1):g}d ago", age_hours


def instagram_code_url(code):
    return f"https://www.instagram.com/p/{code}/" if code else ""


def collect_instagram_instagrapi(account, count=3):
    if InstaClient is None:
        raise RuntimeError("instagrapi is not installed")

    username = account.get("username", "").lstrip("@")
    sessionid = cookie_value("sessionid")

    if not sessionid:
        raise RuntimeError("Instagram sessionid not found in cookies.txt")

    client = InstaClient()
    client.login_by_sessionid(sessionid)

    user = client.user_info_by_username(username)

    stats = empty_stats(account)
    stats.update({
        "followers": getattr(user, "follower_count", None),
        "following": getattr(user, "following_count", None),
        "total_posts": getattr(user, "media_count", None),
        "profile_pic_url": str(getattr(user, "profile_pic_url", "") or ""),
        "source": "instagrapi_session",
        "note": "",
    })

    media_items = client.user_medias(user.pk, amount=count)
    videos = []

    for idx, media in enumerate(media_items[:count], 1):
        timestamp = getattr(media, "taken_at", None)
        posted_ago = "unknown"
        age_hours = 999

        if timestamp:
            try:
                age_hours = round((datetime.now(timestamp.tzinfo) - timestamp).total_seconds() / 3600, 1)
                posted_ago = f"{age_hours:g}h ago" if age_hours < 24 else f"{round(age_hours / 24, 1):g}d ago"
            except Exception:
                pass

        views = getattr(media, "play_count", None) or getattr(media, "view_count", None) or 0

        videos.append({
            "rank": idx,
            "url": instagram_code_url(getattr(media, "code", "")),
            "posted_ago": posted_ago,
            "age_hours": age_hours,
            "views": views,
            "likes": getattr(media, "like_count", 0),
            "comments": getattr(media, "comment_count", 0),
            "shares": 0,
            "caption": str(getattr(media, "caption_text", "") or "")[:160],
            "thumbnail_url": str(getattr(media, "thumbnail_url", "") or ""),
            "type": str(getattr(media, "media_type", "") or ""),
        })

    stats["videos"] = videos
    return finalize_stats(stats)


def collect_instagram_web(account, count=3):
    username = account.get("username", "").lstrip("@")
    session = session_with_cookies()

    headers = dict(DEFAULT_HEADERS)
    headers.update({
        "X-IG-App-ID": "936619743392459",
        "Referer": f"https://www.instagram.com/{username}/",
        "Accept": "*/*",
    })

    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    response = session.get(url, headers=headers, timeout=20)

    if response.status_code != 200:
        raise RuntimeError(f"Instagram web API returned {response.status_code}")

    payload = response.json()
    user = payload.get("data", {}).get("user")

    if not user:
        raise RuntimeError("Instagram web API returned no user")

    stats = empty_stats(account)
    stats.update({
        "followers": user.get("edge_followed_by", {}).get("count"),
        "following": user.get("edge_follow", {}).get("count"),
        "total_posts": user.get("edge_owner_to_timeline_media", {}).get("count"),
        "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        "source": "instagram_web_api",
        "note": "",
    })

    edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])[:count]
    videos = []

    for idx, edge in enumerate(edges, 1):
        node = edge.get("node", {})
        ts = node.get("taken_at_timestamp")
        posted_ago, age_hours = ago_from_timestamp(ts)
        views = node.get("video_view_count") or node.get("video_play_count") or 0

        videos.append({
            "rank": idx,
            "url": f"https://www.instagram.com/p/{node.get('shortcode')}/" if node.get("shortcode") else account.get("url"),
            "posted_ago": posted_ago,
            "age_hours": age_hours,
            "views": views,
            "likes": node.get("edge_liked_by", {}).get("count") or 0,
            "comments": node.get("edge_media_to_comment", {}).get("count") or 0,
            "shares": 0,
            "caption": "",
            "thumbnail_url": node.get("thumbnail_src") or node.get("display_url"),
            "type": "video" if node.get("is_video") else "image",
        })

    stats["videos"] = videos
    return finalize_stats(stats)


def collect_instagram(account, count=3):
    errors = []
    for collector in (collect_instagram_instagrapi, collect_instagram_web):
        try:
            return collector(account, count=count)
        except Exception as e:
            errors.append(f"{collector.__name__}: {type(e).__name__}: {e}")

    stats = empty_stats(account, note="; ".join(errors))
    stats["source"] = "instagram_failed"
    return stats


def find_nested_tiktok_items(obj, found=None):
    if found is None:
        found = []

    if isinstance(obj, dict):
        stats = obj.get("stats") or obj.get("statsV2")
        if isinstance(stats, dict) and any(k in stats for k in ("playCount", "diggCount", "commentCount", "shareCount")):
            found.append(obj)

        for value in obj.values():
            find_nested_tiktok_items(value, found)

    elif isinstance(obj, list):
        for item in obj:
            find_nested_tiktok_items(item, found)

    return found


def collect_tiktok_web(account, count=3):
    username = account.get("username", "").lstrip("@")
    url = account.get("url") or f"https://www.tiktok.com/@{username}"

    session = session_with_cookies()
    headers = dict(DEFAULT_HEADERS)
    headers.update({"Referer": "https://www.tiktok.com/"})

    response = session.get(url, headers=headers, timeout=25)
    if response.status_code != 200:
        raise RuntimeError(f"TikTok returned {response.status_code}")

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    json_text = None
    for script_id in ("__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE"):
        tag = soup.find("script", {"id": script_id})
        if tag and tag.string:
            json_text = tag.string
            break

    if not json_text:
        match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
        if match:
            json_text = unescape(match.group(1))

    if not json_text:
        raise RuntimeError("TikTok hydration JSON not found")

    payload = json.loads(json_text)
    items = find_nested_tiktok_items(payload)

    seen = set()
    unique_items = []

    for item in items:
        item_id = str(item.get("id") or item.get("awemeId") or item.get("video", {}).get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        unique_items.append(item)

    stats = empty_stats(account)
    stats["source"] = "tiktok_web"
    stats["note"] = ""

    videos = []
    for idx, item in enumerate(unique_items[:count], 1):
        raw_stats = item.get("stats") or item.get("statsV2") or {}
        create_time = item.get("createTime") or item.get("create_time")
        posted_ago, age_hours = ago_from_timestamp(create_time)
        item_id = str(item.get("id") or item.get("awemeId") or item.get("video", {}).get("id") or "")
        video_url = f"https://www.tiktok.com/@{username}/video/{item_id}" if item_id else url

        videos.append({
            "rank": idx,
            "url": video_url,
            "posted_ago": posted_ago,
            "age_hours": age_hours,
            "views": raw_stats.get("playCount") or raw_stats.get("play_count") or 0,
            "likes": raw_stats.get("diggCount") or raw_stats.get("digg_count") or 0,
            "comments": raw_stats.get("commentCount") or raw_stats.get("comment_count") or 0,
            "shares": raw_stats.get("shareCount") or raw_stats.get("share_count") or 0,
            "caption": str(item.get("desc") or "")[:160],
            "thumbnail_url": "",
            "type": "video",
        })

    stats["videos"] = videos
    return finalize_stats(stats)


def collect_tiktok(account, count=3):
    try:
        return collect_tiktok_web(account, count=count)
    except Exception as e:
        stats = empty_stats(account, note=f"TikTok collector failed: {type(e).__name__}: {e}")
        stats["source"] = "tiktok_failed"
        return stats


async def add_browser_cookies(context, domain_hint):
    cookies = []
    for name, item in read_netscape_cookies().items():
        domain = item.get("domain") or domain_hint
        value = item.get("value")

        if not value:
            continue

        if domain_hint not in domain and domain not in domain_hint:
            # Keep common cookies out of unrelated domains.
            continue

        cookies.append({
            "name": name,
            "value": value,
            "domain": domain if domain.startswith(".") else domain,
            "path": "/",
        })

    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception:
            pass


async def browser_page_snapshot(url, domain_hint):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 2000},
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="en-US",
        )

        await add_browser_cookies(context, domain_hint)

        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)

        text = await page.locator("body").inner_text(timeout=15000)

        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({href: a.href || '', text: a.innerText || ''})).slice(0, 250)"""
        )

        html = await page.content()

        await browser.close()

    return text, links, html


def extract_count_near(text, labels):
    for label in labels:
        patterns = [
            rf"([0-9][0-9,\.]*\s*[KMBkmb]?)\s+{label}",
            rf"{label}\s+([0-9][0-9,\.]*\s*[KMBkmb]?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                value = parse_count(match.group(1))
                if value is not None:
                    return value

    return None


def links_to_posts(links, platform, username, limit=3):
    urls = []

    for item in links:
        href = item.get("href") or ""

        if platform == "x":
            if "/status/" not in href:
                continue
            if username.lower() not in href.lower():
                continue

        elif platform == "threads":
            if "/post/" not in href:
                continue

        if href not in urls:
            urls.append(href)

        if len(urls) >= limit:
            break

    return urls


async def collect_x_browser(account, count=3):
    username = account.get("username", "").lstrip("@")
    url = account.get("url") or f"https://x.com/{username}"

    text, links, html = await browser_page_snapshot(url, "x.com")

    if "Log in" in text and "Sign up" in text and "Followers" not in text:
        raise RuntimeError("X login wall. Add valid X cookies to cookies.txt")

    stats = empty_stats(account)
    stats["source"] = "x_playwright_cookies"
    stats["note"] = ""

    stats["followers"] = extract_count_near(text, ["Followers"])
    stats["following"] = extract_count_near(text, ["Following"])

    urls = links_to_posts(links, "x", username, count)

    videos = []
    for idx, post_url in enumerate(urls[:count], 1):
        videos.append({
            "rank": idx,
            "url": post_url,
            "posted_ago": "unknown",
            "age_hours": 999,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "caption": "",
            "thumbnail_url": "",
            "type": "post",
        })

    stats["videos"] = videos
    return finalize_stats(stats)


async def collect_threads_browser(account, count=3):
    username = account.get("username", "").lstrip("@")
    url = account.get("url") or f"https://www.threads.net/@{username}"

    text, links, html = await browser_page_snapshot(url, "threads.net")

    stats = empty_stats(account)
    stats["source"] = "threads_playwright_cookies"
    stats["note"] = ""

    stats["followers"] = extract_count_near(text, ["followers", "Followers"])

    urls = links_to_posts(links, "threads", username, count)

    videos = []
    for idx, post_url in enumerate(urls[:count], 1):
        videos.append({
            "rank": idx,
            "url": post_url,
            "posted_ago": "unknown",
            "age_hours": 999,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "caption": "",
            "thumbnail_url": "",
            "type": "post",
        })

    stats["videos"] = videos
    return finalize_stats(stats)


async def collect_account_stats(account, count=3):
    platform = normalize_platform(account.get("platform"))

    if platform == "instagram":
        return await asyncio.to_thread(collect_instagram, account, count)

    if platform == "tiktok":
        return await asyncio.to_thread(collect_tiktok, account, count)

    if platform == "x":
        try:
            return await collect_x_browser(account, count=count)
        except Exception as e:
            stats = empty_stats(account, note=f"X collector failed: {type(e).__name__}: {e}")
            stats["source"] = "x_failed"
            return stats

    if platform == "threads":
        try:
            return await collect_threads_browser(account, count=count)
        except Exception as e:
            stats = empty_stats(account, note=f"Threads collector failed: {type(e).__name__}: {e}")
            stats["source"] = "threads_failed"
            return stats

    stats = empty_stats(account, note=f"Unsupported platform: {platform}")
    stats["source"] = "unsupported"
    return stats
