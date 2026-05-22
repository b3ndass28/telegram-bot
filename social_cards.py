from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from config import DOWNLOAD_DIR


def k_format(num):
    try:
        if num is None:
            return "—"
        num = float(num or 0)
    except Exception:
        return "—"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B".replace(".0B", "B")
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".replace(".0M", "M")
    if num >= 1_000:
        return f"{num / 1_000:.1f}K".replace(".0K", "K")
    return str(int(num))


def platform_label(platform):
    return {
        "instagram": "📸 Instagram",
        "tiktok": "🎵 TikTok",
        "x": "𝕏 X",
        "threads": "🧵 Threads",
    }.get(platform, platform or "Social")


def create_social_card(account, stats, count=0):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    path = DOWNLOAD_DIR / f"social_card_{account['id']}_{count}_{int(datetime.now().timestamp())}.png"

    img = Image.new("RGB", (1200, 760), (10, 13, 24))
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
        med = ImageFont.truetype("DejaVuSans-Bold.ttf", 33)
        font = ImageFont.truetype("DejaVuSans.ttf", 25)
        small = ImageFont.truetype("DejaVuSans.ttf", 21)
    except Exception:
        big = med = font = small = None

    panel = (25, 32, 49)
    box = (38, 47, 68)
    white = (248, 250, 252)
    muted = (163, 174, 194)

    d.rounded_rectangle((40, 35, 1160, 725), radius=34, fill=panel)
    d.text((75, 70), f"{platform_label(account.get('platform'))} @{account.get('username')}", fill=white, font=big)
    d.text((75, 134), f"Status: {stats.get('status')}    Source: {stats.get('source') or 'unknown'}", fill=muted, font=small)

    metrics = [
        ("Followers", k_format(stats.get("followers")), (96, 165, 250)),
        ("Posts", k_format(stats.get("total_posts")), (52, 211, 153)),
        ("Likes", k_format(stats.get("total_likes")), (251, 191, 36)),
        ("Views", k_format(stats.get("total_views")), (248, 113, 113)),
        ("Avg ER", f"{stats.get('avg_er', 0)}%", (196, 181, 253)),
    ]

    x, y = 75, 205
    for label, value, color in metrics:
        d.rounded_rectangle((x, y, x + 200, y + 112), radius=22, fill=box)
        d.text((x + 20, y + 18), label, fill=muted, font=small)
        d.text((x + 20, y + 54), str(value), fill=color, font=med)
        x += 218

    y = 370
    videos = stats.get("videos", [])[:max(0, int(count or 0))]
    if videos:
        for v in videos:
            d.rounded_rectangle((75, y, 1125, y + 94), radius=20, fill=box)
            d.text((105, y + 16), f"#{v.get('rank')}  {v.get('posted_ago', 'unknown')}", fill=white, font=font)
            d.text((300, y + 16), f"Views {k_format(v.get('views'))}", fill=(96, 165, 250), font=font)
            d.text((520, y + 16), f"Likes {k_format(v.get('likes'))}", fill=(52, 211, 153), font=font)
            d.text((735, y + 16), f"ER {v.get('er', 0)}%", fill=(196, 181, 253), font=font)
            d.text((900, y + 16), f"{v.get('potential', 'Low')}", fill=(251, 191, 36), font=font)
            y += 112
    else:
        note = stats.get("note") or "Profile summary loaded. Press Latest / Last 3 for post details."
        d.rounded_rectangle((75, y, 1125, y + 120), radius=20, fill=box)
        d.text((105, y + 25), note[:88], fill=muted, font=font)
        d.text((105, y + 66), "Quick snapshot card for fast checking / forwarding.", fill=muted, font=small)

    d.text((75, 670), f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fill=muted, font=small)
    img.save(path, quality=95)
    return str(path)
