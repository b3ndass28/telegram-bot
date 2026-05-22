from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from config import DOWNLOAD_DIR


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def k_format(num):
    try:
        num = float(num or 0)
    except Exception:
        return "0"

    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".replace(".0M", "M")
    if num >= 1_000:
        return f"{num / 1_000:.1f}K".replace(".0K", "K")
    return str(int(num))


def platform_label(platform):
    if platform == "instagram":
        return "📸 Instagram"
    if platform == "tiktok":
        return "🎵 TikTok"
    if platform == "x":
        return "𝕏 X"
    return platform or "Social"


def create_social_card(account, stats, count=3):
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    path = DOWNLOAD_DIR / f"social_card_{account['id']}_{count}.png"

    width, height = 1200, 760
    img = Image.new("RGB", (width, height), (18, 21, 31))
    draw = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
        font_med = ImageFont.truetype("DejaVuSans-Bold.ttf", 32)
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 21)
    except Exception:
        font_big = font_med = font = font_small = None

    panel = (28, 34, 49)
    box = (38, 45, 64)
    text = (245, 247, 250)
    muted = (160, 170, 190)
    accent = (76, 141, 255)
    green = (53, 195, 126)
    yellow = (255, 201, 77)
    red = (255, 120, 120)

    draw.rounded_rectangle((40, 35, width - 40, height - 35), radius=32, fill=panel)

    draw.text(
        (75, 70),
        f"{platform_label(account.get('platform'))} @{account.get('username')}",
        fill=text,
        font=font_big
    )

    title = "Latest video summary" if count == 1 else f"Last {count} videos summary"
    draw.text((75, 132), title, fill=muted, font=font)

    boxes = [
        ("Views", k_format(stats.get("total_views")), accent),
        ("Likes", k_format(stats.get("total_likes")), green),
        ("Comments", k_format(stats.get("total_comments")), yellow),
        ("Shares", k_format(stats.get("total_shares")), red),
        ("Avg ER", f"{stats.get('avg_er', 0)}%", (190, 130, 255)),
    ]

    x, y = 75, 205
    for label, value, color in boxes:
        draw.rounded_rectangle((x, y, x + 200, y + 110), radius=22, fill=box)
        draw.text((x + 20, y + 18), label, fill=muted, font=font_small)
        draw.text((x + 20, y + 52), value, fill=color, font=font_med)
        x += 218

    y = 360
    videos = stats.get("videos", [])[:count]

    if not videos:
        draw.text((75, y), "No public stats available yet.", fill=muted, font=font_med)
        draw.text((75, y + 50), stats.get("note", ""), fill=muted, font=font_small)
    else:
        for v in videos:
            potential = v.get("potential", "Low")
            potential_color = green if potential == "High" else yellow if potential == "Medium" else red

            draw.rounded_rectangle((75, y, width - 75, y + 95), radius=20, fill=box)

            draw.text((105, y + 18), f"#{v.get('rank')}  {v.get('posted_ago', 'unknown')}", fill=text, font=font)
            draw.text((265, y + 18), f"Views {k_format(v.get('views'))}", fill=accent, font=font)
            draw.text((470, y + 18), f"Likes {k_format(v.get('likes'))}", fill=green, font=font)
            draw.text((675, y + 18), f"ER {v.get('er', 0)}%", fill=(190, 130, 255), font=font)
            draw.text((855, y + 18), f"Potential {potential}", fill=potential_color, font=font)
            draw.text(
                (105, y + 55),
                f"Comments {k_format(v.get('comments'))}   Shares {k_format(v.get('shares'))}",
                fill=muted,
                font=font_small
            )

            y += 112

    draw.text((75, height - 90), f"Updated: {current_timestamp()}", fill=muted, font=font_small)

    img.save(path, quality=95)
    return str(path)
