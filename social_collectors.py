import asyncio
import json
import re
import time
from datetime import datetime
from html import unescape
from pathlib import Path

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
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def now_str():
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


def platform_url(platform, username):
    platform = normalize_platform(platform)
    username = (username or "").lstrip("@").strip("/")
    if platform == "instagram":
        return f"https://www.instagram.com/{username}/"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{username}"
    if platform == "x":
        return f"https://x.com/{username}"
    if platform == "threads":
        return f"https://www.threads.net/@{username}"
    return username


def parse_count(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("\u00a0", " ").replace(",", "").replace(" ", "")
    if not text or text in {"—", "-"}:
        return None
    multiplier = 1
    low = text.lower()
    if low.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif low.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    elif low.endswith("b"):
        multiplier, text = 1_000_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except Exception:
        return None


def safe_int(value):
    return int(parse_count(value) or 0)


def calc_er(views, likes, comments, shares):
    views = float(views or 0)
    if views <= 0:
        return 0
    return round(((float(likes or 0) + float(comments or 0) + float(shares or 0)) / views) * 100, 2)


def empty_stats(account, note="Public profile stats unavailable."):
    platform = normalize_platform(account.get("platform"))
    username = (account.get("username") or "").lstrip("@")
    return {
        "platform": platform,
        "username": username,
        "url": account.get("url") or platform_url(platform, username),
        "profile_pic_url": None,
        "followers": None,
        "following": None,
        "total_posts": None,
        "total_likes": None,
        "total_views": None,
        "total_comments": 0,
        "total_shares": 0,
        "avg_er": 0,
        "videos": [],
        "status": "unavailable",
        "source": None,
        "note": note,
        "collected_at": now_str(),
        "profile_only": True,
    }


def finalize_stats(stats):
    videos = stats.get("videos", []) or []
    for v in videos:
        v["views"] = safe_int(v.get("views"))
        v["likes"] = safe_int(v.get("likes"))
        v["comments"] = safe_int(v.get("comments"))
        v["shares"] = safe_int(v.get("shares"))
        v["er"] = calc_er(v["views"], v["likes"], v["comments"], v["shares"])
        if v["views"] >= 10000 and v["er"] >= 5:
            v["potential"], v["potential_reason"] = "High", "views + engagement"
        elif v["views"] >= 1000 or v["er"] >= 2:
            v["potential"], v["potential_reason"] = "Medium", "some traction"
        else:
            v["potential"], v["potential_reason"] = "Low", "weak public signals"

    if videos:
        stats["total_views"] = sum(v["views"] for v in videos)
        stats["total_likes"] = sum(v["likes"] for v in videos)
        stats["total_comments"] = sum(v["comments"] for v in videos)
        stats["total_shares"] = sum(v["shares"] for v in videos)
        stats["avg_er"] = round(sum(float(v.get("er") or 0) for v in videos) / len(videos), 2)
        stats["profile_only"] = False

    if (
        stats.get("followers") is not None
        or stats.get("total_likes") is not None
        or stats.get("total_posts") is not None
        or videos
    ):
        stats["status"] = "ok"
    else:
        stats["status"] = "unavailable"
    return stats


def read_cookies():
    cookies = {}
    path = Path(COOKIES_FILE)
    if not path.exists():
        return cookies
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5].strip()] = {"value": parts[6].strip(), "domain": parts[0].strip()}
        elif "=" in line:
            name, value = line.split("=", 1)
            cookies[name.strip()] = {"value": value.strip(), "domain": ""}
    return cookies


def cookie_value(name):
    item = read_cookies().get(name)
    return item.get("value") if item else None


def make_session():
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    for name, item in read_cookies().items():
        try:
            session.cookies.set(name, item.get("value"), domain=item.get("domain") or None)
        except Exception:
            session.cookies.set(name, item.get("value"))
    return session


def ago_from_timestamp(ts):
    try:
        ts = float(ts)
    except Exception:
        return "unknown", 999
    age = round((time.time() - ts) / 3600, 1)
    return (f"{age:g}h ago", age) if age < 24 else (f"{round(age / 24, 1):g}d ago", age)


def extract_count_near(text, labels):
    clean = text.replace("\n", " ")
    for label in labels:
        for pattern in (rf"([0-9][0-9,\.]*\s*[KMBkmb]?)\s+{label}", rf"{label}\s+([0-9][0-9,\.]*\s*[KMBkmb]?)"):
            m = re.search(pattern, clean, re.I)
            if m:
                val = parse_count(m.group(1))
                if val is not None:
                    return val
    return None


def extract_json_script(html):
    soup = BeautifulSoup(html, "html.parser")
    for script_id in ("__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE"):
        tag = soup.find("script", {"id": script_id})
        if tag and tag.string:
            return tag.string
    match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        return unescape(match.group(1))
    return None


def deep_find_dicts(obj, keys, results=None):
    if results is None:
        results = []
    if isinstance(obj, dict):
        if any(k in obj for k in keys):
            results.append(obj)
        for value in obj.values():
            deep_find_dicts(value, keys, results)
    elif isinstance(obj, list):
        for item in obj:
            deep_find_dicts(item, keys, results)
    return results


async def add_browser_cookies(context, domain_hint):
    cookies = []
    for name, item in read_cookies().items():
        domain = item.get("domain") or domain_hint
        value = item.get("value")
        if not value:
            continue
        if domain_hint not in domain and domain not in domain_hint:
            continue
        cookies.append({"name": name, "value": value, "domain": domain if domain.startswith(".") else domain, "path": "/"})
    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception:
            pass


async def browser_snapshot(url, domain_hint, wait_ms=4500):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1800},
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="en-US",
        )
        await add_browser_cookies(context, domain_hint)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(wait_ms)
        text = await page.locator("body").inner_text(timeout=15000)
        html = await page.content()
        links = await page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({href: a.href || '', text: a.innerText || ''})).slice(0, 300)"""
        )
        await browser.close()
    return text, html, links


# Instagram

def instagram_profile_instagrapi(account):
    if InstaClient is None:
        raise RuntimeError("instagrapi is not installed")
    sessionid = cookie_value("sessionid")
    if not sessionid:
        raise RuntimeError("Instagram sessionid missing in cookies.txt")
    username = account.get("username", "").lstrip("@")
    client = InstaClient()
    client.login_by_sessionid(sessionid)
    user = client.user_info_by_username(username)
    stats = empty_stats(account)
    stats.update({
        "followers": getattr(user, "follower_count", None),
        "following": getattr(user, "following_count", None),
        "total_posts": getattr(user, "media_count", None),
        "profile_pic_url": str(getattr(user, "profile_pic_url", "") or ""),
        "source": "instagram:instagrapi_profile",
        "note": "",
    })
    return finalize_stats(stats)


def instagram_profile_web(account):
    username = account.get("username", "").lstrip("@")
    session = make_session()
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
    user = response.json().get("data", {}).get("user")
    if not user:
        raise RuntimeError("Instagram web API returned no user")
    stats = empty_stats(account)
    stats.update({
        "followers": user.get("edge_followed_by", {}).get("count"),
        "following": user.get("edge_follow", {}).get("count"),
        "total_posts": user.get("edge_owner_to_timeline_media", {}).get("count"),
        "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        "source": "instagram:web_profile_info",
        "note": "",
    })
    return finalize_stats(stats)


async def instagram_profile_playwright(account):
    username = account.get("username", "").lstrip("@")
    text, html, links = await browser_snapshot(account.get("url") or platform_url("instagram", username), "instagram.com")
    stats = empty_stats(account)
    stats.update({
        "followers": extract_count_near(text, ["followers", "Followers"]),
        "following": extract_count_near(text, ["following", "Following"]),
        "total_posts": extract_count_near(text, ["posts", "Posts"]),
        "source": "instagram:playwright_profile",
        "note": "",
    })
    return finalize_stats(stats)


def instagram_recent_instagrapi(account, count=3):
    if InstaClient is None:
        raise RuntimeError("instagrapi is not installed")
    sessionid = cookie_value("sessionid")
    if not sessionid:
        raise RuntimeError("Instagram sessionid missing in cookies.txt")
    username = account.get("username", "").lstrip("@")
    client = InstaClient()
    client.login_by_sessionid(sessionid)
    user = client.user_info_by_username(username)
    base = instagram_profile_instagrapi(account)
    medias = client.user_medias(user.pk, amount=count)
    videos = []
    for i, media in enumerate(medias[:count], 1):
        taken = getattr(media, "taken_at", None)
        posted, age = "unknown", 999
        if taken:
            try:
                age = round((datetime.now(taken.tzinfo) - taken).total_seconds() / 3600, 1)
                posted = f"{age:g}h ago" if age < 24 else f"{round(age / 24, 1):g}d ago"
            except Exception:
                pass
        code = getattr(media, "code", "")
        videos.append({
            "rank": i,
            "url": f"https://www.instagram.com/p/{code}/" if code else base["url"],
            "posted_ago": posted,
            "age_hours": age,
            "views": getattr(media, "play_count", None) or getattr(media, "view_count", None) or 0,
            "likes": getattr(media, "like_count", 0),
            "comments": getattr(media, "comment_count", 0),
            "shares": 0,
            "caption": str(getattr(media, "caption_text", "") or "")[:160],
            "thumbnail_url": str(getattr(media, "thumbnail_url", "") or ""),
            "type": "instagram_media",
        })
    base["videos"] = videos
    return finalize_stats(base)


async def instagram_profile(account):
    errors = []
    for fn in (instagram_profile_instagrapi, instagram_profile_web):
        try:
            return fn(account)
        except Exception as e:
            errors.append(f"{fn.__name__}: {type(e).__name__}: {e}")
    try:
        return await instagram_profile_playwright(account)
    except Exception as e:
        errors.append(f"instagram_profile_playwright: {type(e).__name__}: {e}")
    stats = empty_stats(account, "; ".join(errors))
    stats["source"] = "instagram:failed"
    return stats


async def instagram_recent(account, count=3):
    try:
        return instagram_recent_instagrapi(account, count=count)
    except Exception as e:
        stats = await instagram_profile(account)
        stats["note"] = f"Recent posts unavailable: {type(e).__name__}: {e}. {stats.get('note') or ''}"
        return stats


# TikTok

def tiktok_payload(account):
    username = account.get("username", "").lstrip("@")
    url = account.get("url") or platform_url("tiktok", username)
    session = make_session()
    headers = dict(DEFAULT_HEADERS)
    headers.update({"Referer": "https://www.tiktok.com/"})
    response = session.get(url, headers=headers, timeout=25)
    if response.status_code != 200:
        raise RuntimeError(f"TikTok returned {response.status_code}")
    script = extract_json_script(response.text)
    if not script:
        raise RuntimeError("TikTok hydration JSON not found")
    return json.loads(script)


def find_tiktok_profile(payload, username):
    username = username.lower().lstrip("@")
    candidates = deep_find_dicts(payload, ["uniqueId", "followerCount", "heartCount", "videoCount", "followingCount"])
    best = None
    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        stats = obj.get("stats") or obj.get("statsV2") or obj
        uid = str(obj.get("uniqueId") or obj.get("unique_id") or "").lower()
        if uid == username or any(k in stats for k in ("followerCount", "heartCount", "videoCount")):
            best = obj
            if uid == username:
                break
    return best


def find_tiktok_items(payload):
    items = []
    for obj in deep_find_dicts(payload, ["playCount", "diggCount", "commentCount", "shareCount"]):
        stats = obj.get("stats") or obj.get("statsV2") or obj
        if isinstance(stats, dict) and any(k in stats for k in ("playCount", "diggCount", "commentCount", "shareCount")):
            items.append(obj)
    seen, result = set(), []
    for item in items:
        item_id = str(item.get("id") or item.get("awemeId") or item.get("video", {}).get("id") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item)
    return result



def tiktok_find_userinfo(payload, username):
    """
    TikTok often stores profile stats under:
    __DEFAULT_SCOPE__ -> webapp.user-detail -> userInfo -> {user, stats}
    This function searches for that shape first, then falls back to recursive candidates.
    """
    username = username.lower().lstrip("@")

    # Direct known path
    try:
        default_scope = payload.get("__DEFAULT_SCOPE__", {})
        for key, value in default_scope.items():
            if "user-detail" in key and isinstance(value, dict):
                user_info = value.get("userInfo") or value.get("user_info")
                if isinstance(user_info, dict):
                    user = user_info.get("user", {})
                    stats = user_info.get("stats", {}) or user_info.get("statsV2", {})
                    uid = str(user.get("uniqueId") or user.get("unique_id") or "").lower()
                    if stats and (uid == username or not username):
                        return user, stats
    except Exception:
        pass

    # Recursive fallback
    candidates = deep_find_dicts(payload, ["userInfo", "user_info", "stats", "statsV2", "followerCount", "heartCount", "videoCount"])
    for obj in candidates:
        if not isinstance(obj, dict):
            continue

        user_info = obj.get("userInfo") or obj.get("user_info")
        if isinstance(user_info, dict):
            user = user_info.get("user", {})
            stats = user_info.get("stats", {}) or user_info.get("statsV2", {})
            uid = str(user.get("uniqueId") or user.get("unique_id") or "").lower()
            if stats and (uid == username or not username):
                return user, stats

        stats = obj.get("stats") or obj.get("statsV2")
        if isinstance(stats, dict):
            uid = str(obj.get("uniqueId") or obj.get("unique_id") or obj.get("user", {}).get("uniqueId") or "").lower()
            if any(k in stats for k in ("followerCount", "heartCount", "videoCount")) and (uid == username or not uid):
                return obj.get("user", obj), stats

        if any(k in obj for k in ("followerCount", "heartCount", "videoCount")):
            return obj, obj

    return None, None


def tiktok_parse_meta_counts(html):
    """
    Last-resort parser for TikTok meta text like:
    '237.7K Followers, 120 Following, 2.1M Likes...'
    """
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    stats = {}

    followers = extract_count_near(text, ["Followers", "followers"])
    following = extract_count_near(text, ["Following", "following"])
    likes = extract_count_near(text, ["Likes", "likes"])
    videos = extract_count_near(text, ["Videos", "videos", "Posts", "posts"])

    if followers is not None:
        stats["followers"] = followers
    if following is not None:
        stats["following"] = following
    if likes is not None:
        stats["total_likes"] = likes
    if videos is not None:
        stats["total_posts"] = videos

    return stats


async def tiktok_profile_playwright(account):
    username = account.get("username", "").lstrip("@")
    text, html, links = await browser_snapshot(account.get("url") or platform_url("tiktok", username), "tiktok.com", wait_ms=6500)

    stats = empty_stats(account)
    stats["source"] = "tiktok:playwright_profile"
    stats["note"] = ""

    stats["followers"] = extract_count_near(text, ["Followers", "followers"])
    stats["following"] = extract_count_near(text, ["Following", "following"])
    stats["total_likes"] = extract_count_near(text, ["Likes", "likes"])
    stats["total_posts"] = extract_count_near(text, ["Videos", "videos", "Posts", "posts"])

    return finalize_stats(stats)




def tiktok_profile(account):
    username = account.get("username", "").lstrip("@")
    stats = empty_stats(account)

    try:
        payload = tiktok_payload(account)
        user, profile_stats = tiktok_find_userinfo(payload, username)

        stats["source"] = "tiktok:hydration_profile"
        stats["note"] = ""

        if profile_stats:
            stats.update({
                "followers": parse_count(profile_stats.get("followerCount") or profile_stats.get("follower_count")),
                "following": parse_count(profile_stats.get("followingCount") or profile_stats.get("following_count")),
                "total_posts": parse_count(profile_stats.get("videoCount") or profile_stats.get("video_count")),
                "total_likes": parse_count(profile_stats.get("heartCount") or profile_stats.get("heart") or profile_stats.get("diggCount")),
                "profile_pic_url": (user or {}).get("avatarLarger") or (user or {}).get("avatarMedium") or (user or {}).get("avatarThumb"),
            })
            return finalize_stats(stats)

        # If JSON exists but shape changed, try meta/body text fallback from the same page.
        url = account.get("url") or platform_url("tiktok", username)
        response = make_session().get(url, headers=dict(DEFAULT_HEADERS, Referer="https://www.tiktok.com/"), timeout=25)
        meta_stats = tiktok_parse_meta_counts(response.text)
        if meta_stats:
            stats.update(meta_stats)
            stats["source"] = "tiktok:meta_profile"
            stats["note"] = ""
            return finalize_stats(stats)

        stats["source"] = "tiktok:hydration_profile"
        stats["note"] = "TikTok page loaded, but profile counters were not found in hydration JSON."
        return finalize_stats(stats)

    except Exception as e:
        stats["source"] = "tiktok:hydration_failed"
        stats["note"] = f"TikTok hydration failed: {type(e).__name__}: {e}"
        return finalize_stats(stats)


def tiktok_recent(account, count=3):
    username = account.get("username", "").lstrip("@")
    payload = tiktok_payload(account)
    stats = tiktok_profile(account)
    stats["source"] = "tiktok:hydration_recent"
    videos = []
    for i, item in enumerate(find_tiktok_items(payload)[:count], 1):
        raw = item.get("stats") or item.get("statsV2") or item
        posted, age = ago_from_timestamp(item.get("createTime") or item.get("create_time"))
        item_id = str(item.get("id") or item.get("awemeId") or item.get("video", {}).get("id") or "")
        videos.append({
            "rank": i,
            "url": f"https://www.tiktok.com/@{username}/video/{item_id}" if item_id else stats["url"],
            "posted_ago": posted,
            "age_hours": age,
            "views": raw.get("playCount") or raw.get("play_count") or 0,
            "likes": raw.get("diggCount") or raw.get("digg_count") or 0,
            "comments": raw.get("commentCount") or raw.get("comment_count") or 0,
            "shares": raw.get("shareCount") or raw.get("share_count") or 0,
            "caption": str(item.get("desc") or "")[:160],
            "thumbnail_url": "",
            "type": "tiktok_video",
        })
    stats["videos"] = videos
    return finalize_stats(stats)


# X / Threads

async def x_profile(account):
    username = account.get("username", "").lstrip("@")
    text, html, links = await browser_snapshot(account.get("url") or platform_url("x", username), "x.com")
    stats = empty_stats(account)
    stats.update({
        "followers": extract_count_near(text, ["Followers"]),
        "following": extract_count_near(text, ["Following"]),
        "source": "x:playwright_profile",
        "note": "",
    })
    return finalize_stats(stats)


async def threads_profile(account):
    username = account.get("username", "").lstrip("@")
    text, html, links = await browser_snapshot(account.get("url") or platform_url("threads", username), "threads.net")
    stats = empty_stats(account)
    stats.update({
        "followers": extract_count_near(text, ["followers", "Followers"]),
        "source": "threads:playwright_profile",
        "note": "",
    })
    return finalize_stats(stats)


async def collect_profile_stats(account):
    platform = normalize_platform(account.get("platform"))
    try:
        if platform == "instagram":
            return await instagram_profile(account)
        if platform == "tiktok":
            stats = await asyncio.to_thread(tiktok_profile, account)
            if stats.get("status") == "ok":
                return stats
            # Browser fallback catches pages where requests gets an empty/changed hydration object.
            fallback = await tiktok_profile_playwright(account)
            if fallback.get("status") == "ok":
                return fallback
            fallback["note"] = (fallback.get("note") or "") + " | " + (stats.get("note") or "")
            return fallback
        if platform == "x":
            return await x_profile(account)
        if platform == "threads":
            return await threads_profile(account)
        stats = empty_stats(account, f"Unsupported platform: {platform}")
        stats["source"] = "unsupported"
        return stats
    except Exception as e:
        stats = empty_stats(account, f"{platform} profile collector failed: {type(e).__name__}: {e}")
        stats["source"] = f"{platform}:failed"
        return stats


async def collect_recent_stats(account, count=3):
    platform = normalize_platform(account.get("platform"))
    count = max(1, min(int(count or 3), 3))
    try:
        if platform == "instagram":
            return await instagram_recent(account, count)
        if platform == "tiktok":
            return await asyncio.to_thread(tiktok_recent, account, count)
        if platform == "x":
            stats = await x_profile(account)
            stats["note"] = "Recent X post metrics require a stable logged-in collector/API. Profile stats loaded."
            return stats
        if platform == "threads":
            stats = await threads_profile(account)
            stats["note"] = "Recent Threads post metrics require a stable logged-in collector/API. Profile stats loaded."
            return stats
        stats = empty_stats(account, f"Unsupported platform: {platform}")
        stats["source"] = "unsupported"
        return stats
    except Exception as e:
        stats = await collect_profile_stats(account)
        stats["note"] = f"Recent collector failed: {type(e).__name__}: {e}. {stats.get('note') or ''}"
        return stats
