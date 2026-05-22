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
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "x": "X",
        "threads": "Threads",
    }.get(platform, platform or "Social")


def _font(name="DejaVuSans.ttf", size=40):
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return None


def _wrap(draw, text, font, max_width):
    words = str(text or "").split()
    lines, line = [], ""
    for word in words:
        test = (line + " " + word).strip()
        try:
            width = draw.textbbox((0, 0), test, font=font)[2]
        except Exception:
            width = len(test) * 12
        if width <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def create_social_card(account, stats, count=0):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    path = DOWNLOAD_DIR / f"social_card_{account['id']}_{count}_{int(datetime.now().timestamp())}.png"

    # 4:5 vertical card, readable in Telegram preview.
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), (10, 14, 25))
    d = ImageDraw.Draw(img)

    title_font = _font("DejaVuSans-Bold.ttf", 58)
    sub_font = _font("DejaVuSans.ttf", 28)
    label_font = _font("DejaVuSans.ttf", 28)
    value_font = _font("DejaVuSans-Bold.ttf", 52)
    small_font = _font("DejaVuSans.ttf", 25)
    tiny_font = _font("DejaVuSans.ttf", 22)

    bg2 = (17, 24, 39)
    panel = (30, 41, 59)
    card = (42, 55, 78)
    white = (248, 250, 252)
    muted = (177, 187, 205)
    blue = (96, 165, 250)
    green = (52, 211, 153)
    yellow = (251, 191, 36)
    red = (248, 113, 113)
    purple = (196, 181, 253)

    d.rounded_rectangle((36, 36, W - 36, H - 36), radius=44, fill=bg2)

    platform = platform_label(account.get("platform"))
    username = account.get("username")
    d.text((78, 86), platform, fill=muted, font=sub_font)
    d.text((78, 128), f"@{username}", fill=white, font=title_font)

    status = stats.get("status") or "unknown"
    source = stats.get("source") or "unknown"
    d.rounded_rectangle((78, 220, W - 78, 285), radius=20, fill=panel)
    d.text((105, 238), f"Status: {status}   ·   Source: {source}", fill=muted, font=tiny_font)

    metrics = [
        ("Followers", k_format(stats.get("followers")), blue),
        ("Posts", k_format(stats.get("total_posts")), green),
        ("Likes", k_format(stats.get("total_likes")), yellow),
        ("Views", k_format(stats.get("total_views")), red),
        ("Avg ER", f"{stats.get('avg_er', 0)}%", purple),
    ]

    x0, y0 = 78, 335
    box_w, box_h = 440, 160
    gap = 30

    for i, (label, value, color) in enumerate(metrics[:4]):
        x = x0 + (i % 2) * (box_w + gap)
        y = y0 + (i // 2) * (box_h + gap)
        d.rounded_rectangle((x, y, x + box_w, y + box_h), radius=28, fill=card)
        d.text((x + 32, y + 28), label, fill=muted, font=label_font)
        d.text((x + 32, y + 78), str(value), fill=color, font=value_font)

    # ER full width
    y = y0 + 2 * (box_h + gap)
    d.rounded_rectangle((x0, y, W - 78, y + 135), radius=28, fill=card)
    d.text((x0 + 32, y + 28), "Average Engagement Rate", fill=muted, font=label_font)
    d.text((x0 + 32, y + 68), str(metrics[4][1]), fill=purple, font=value_font)

    y += 175
    videos = stats.get("videos", [])[:max(0, int(count or 0))]

    if videos:
        d.text((78, y), "Recent posts", fill=white, font=_font("DejaVuSans-Bold.ttf", 42))
        y += 65
        for v in videos[:3]:
            d.rounded_rectangle((78, y, W - 78, y + 135), radius=26, fill=card)
            d.text((108, y + 22), f"#{v.get('rank')} · {v.get('posted_ago', 'unknown')}", fill=white, font=small_font)
            line = f"Views {k_format(v.get('views'))}   Likes {k_format(v.get('likes'))}   ER {v.get('er', 0)}%"
            d.text((108, y + 66), line, fill=muted, font=small_font)
            d.text((108, y + 100), f"Potential: {v.get('potential', 'Low')}", fill=yellow, font=tiny_font)
            y += 155
    else:
        note = stats.get("note") or "Profile summary loaded. Press Latest / Last 3 for detailed post stats."
        d.rounded_rectangle((78, y, W - 78, y + 250), radius=28, fill=card)
        d.text((108, y + 30), "Note", fill=white, font=_font("DejaVuSans-Bold.ttf", 38))
        yy = y + 86
        for line in _wrap(d, note, small_font, W - 220)[:4]:
            d.text((108, yy), line, fill=muted, font=small_font)
            yy += 36

    d.text((78, H - 105), f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fill=muted, font=tiny_font)
    img.save(path, quality=96)
    return str(path)
