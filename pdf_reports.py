from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from config import DOWNLOAD_DIR
from social_cards import k_format, platform_label


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_social_pdf(accounts, stats_by_account, title="Social Report"):
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    path = DOWNLOAD_DIR / f"social_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(f"Generated: {current_timestamp()}", styles["Normal"]))
    story.append(Spacer(1, 16))

    total_views = sum(stats_by_account.get(a["id"], {}).get("total_views", 0) for a in accounts)
    total_likes = sum(stats_by_account.get(a["id"], {}).get("total_likes", 0) for a in accounts)
    total_comments = sum(stats_by_account.get(a["id"], {}).get("total_comments", 0) for a in accounts)
    total_shares = sum(stats_by_account.get(a["id"], {}).get("total_shares", 0) for a in accounts)

    summary_rows = [
        ["Accounts", str(len(accounts))],
        ["Total Views", k_format(total_views)],
        ["Total Likes", k_format(total_likes)],
        ["Total Comments", k_format(total_comments)],
        ["Total Shares", k_format(total_shares)],
    ]

    summary_table = Table(summary_rows, colWidths=[180, 250])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 20))

    for acc in accounts:
        stats = stats_by_account.get(acc["id"], {})

        story.append(Paragraph(f"{platform_label(acc.get('platform'))} @{acc.get('username')}", styles["Heading2"]))
        story.append(Paragraph(f"URL: {acc.get('url')}", styles["Normal"]))

        rows = [["#", "Age", "Views", "Likes", "Comments", "Shares", "ER", "Potential"]]

        for v in stats.get("videos", []):
            rows.append([
                str(v.get("rank", "")),
                str(v.get("posted_ago", "")),
                k_format(v.get("views")),
                k_format(v.get("likes")),
                k_format(v.get("comments")),
                k_format(v.get("shares")),
                f"{v.get('er', 0)}%",
                v.get("potential", "")
            ])

        if len(rows) == 1:
            rows.append(["-", "-", "-", "-", "-", "-", "-", "Data unavailable"])

        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))

        story.append(table)
        story.append(Spacer(1, 18))

    doc.build(story)

    return str(path)
