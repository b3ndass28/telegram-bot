from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)

from config import DOWNLOAD_DIR
from social_cards import k_format, platform_label


def safe_num(value):
    try:
        if value is None:
            return 0
        return int(float(value))
    except Exception:
        return 0


def pct(value):
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "0.00%"


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=25, leading=31, textColor=colors.HexColor("#0F172A"), alignment=TA_CENTER, spaceAfter=10),
        "subtitle": ParagraphStyle("subtitle", parent=base["BodyText"], fontSize=9, leading=12, textColor=colors.HexColor("#64748B"), alignment=TA_CENTER),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=18, leading=24, textColor=colors.HexColor("#111827"), spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, leading=17, textColor=colors.HexColor("#334155"), spaceAfter=7),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9.4, leading=12.5, textColor=colors.HexColor("#334155")),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontSize=7.8, leading=10, textColor=colors.HexColor("#64748B")),
        "card_value": ParagraphStyle("card_value", parent=base["BodyText"], fontSize=15, leading=18, textColor=colors.HexColor("#0F172A"), alignment=TA_CENTER),
        "card_label": ParagraphStyle("card_label", parent=base["BodyText"], fontSize=7.5, leading=9, textColor=colors.HexColor("#64748B"), alignment=TA_CENTER),
    }


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0F172A"))
    canvas.rect(0, 285 * mm, 210 * mm, 12 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.white)
    canvas.drawString(14 * mm, 289 * mm, "Social Analytics Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(196 * mm, 289 * mm, f"Page {canvas.getPageNumber()}")
    canvas.setFillColor(colors.HexColor("#94A3B8"))
    canvas.drawString(14 * mm, 9 * mm, f"Generated: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    canvas.restoreState()


def metric_card(label, value):
    s = make_styles()
    return Table(
        [[Paragraph(str(value), s["card_value"])], [Paragraph(label, s["card_label"])]],
        colWidths=[36 * mm],
        rowHeights=[12 * mm, 7 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#E2E8F0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )


def metrics_row(items):
    return Table([[metric_card(label, value) for label, value in items]], hAlign="CENTER")


def chart_path(name):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in name)
    return DOWNLOAD_DIR / f"chart_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"


def bar_chart(title, labels, values, ylabel=""):
    path = chart_path(title)
    labels = labels or ["No data"]
    values = values or [0]

    plt.figure(figsize=(7.2, 3.1))
    bars = plt.bar(labels, values)
    plt.title(title, fontsize=13, fontweight="bold")
    plt.ylabel(ylabel)
    plt.xticks(rotation=18, ha="right", fontsize=8)
    plt.yticks(fontsize=8)
    plt.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), k_format(value), ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()
    return str(path)


def pie_chart(title, labels, values):
    path = chart_path(title)
    pairs = [(l, safe_num(v)) for l, v in zip(labels, values) if safe_num(v) > 0]
    if not pairs:
        pairs = [("No data", 1)]
    labels, values = zip(*pairs)

    plt.figure(figsize=(5.0, 3.6))
    plt.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, textprops={"fontsize": 8})
    plt.title(title, fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()
    return str(path)


def account_rows(accounts, stats_by_account):
    rows = [["Аккаунт", "Платформа", "Followers", "Posts", "Likes", "Views", "ER", "Status"]]
    for acc in accounts:
        st = stats_by_account.get(acc["id"], {})
        rows.append([
            f"@{acc.get('username')}",
            platform_label(acc.get("platform")),
            k_format(st.get("followers")),
            k_format(st.get("total_posts")),
            k_format(st.get("total_likes")),
            k_format(st.get("total_views")),
            pct(st.get("avg_er", 0)),
            st.get("status", "unknown"),
        ])
    return rows


def account_table(accounts, stats_by_account):
    t = Table(account_rows(accounts, stats_by_account), repeatRows=1, colWidths=[33*mm, 25*mm, 24*mm, 18*mm, 24*mm, 24*mm, 16*mm, 23*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    return t


def create_social_pdf(accounts, stats_by_account, title="Social Report"):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    path = DOWNLOAD_DIR / f"social_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=13*mm, leftMargin=13*mm, topMargin=18*mm, bottomMargin=16*mm)
    s = make_styles()
    story = []

    total_followers = sum(safe_num(stats_by_account.get(a["id"], {}).get("followers")) for a in accounts)
    total_likes = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_likes")) for a in accounts)
    total_posts = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_posts")) for a in accounts)
    total_views = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_views")) for a in accounts)
    ok_accounts = sum(1 for a in accounts if stats_by_account.get(a["id"], {}).get("status") == "ok")

    story.append(Spacer(1, 10))
    story.append(Paragraph("Отчёт по аккаунтам", s["title"]))
    story.append(Paragraph(f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}", s["subtitle"]))
    story.append(Spacer(1, 13))
    story.append(Paragraph("Обзор", s["h1"]))
    story.append(Paragraph("Сводка по аккаунтам. PDF берёт последние сохранённые snapshots, поэтому открытие отчёта не тратит новые запросы.", s["body"]))
    story.append(Spacer(1, 10))
    story.append(metrics_row([
        ("Подписчики", k_format(total_followers)),
        ("Лайки", k_format(total_likes)),
        ("Публикации", k_format(total_posts)),
        ("Просмотры", k_format(total_views)),
        ("С данными", f"{ok_accounts}/{len(accounts)}"),
    ]))
    story.append(Spacer(1, 14))

    platforms = {}
    for acc in accounts:
        platforms.setdefault(acc.get("platform"), []).append(acc)

    story.append(Paragraph("Оглавление", s["h2"]))
    for p, items in platforms.items():
        story.append(Paragraph(f"{platform_label(p)} — {len(items)} аккаунт(ов)", s["body"]))
    story.append(Paragraph("Сравнение аккаунтов", s["body"]))
    story.append(Paragraph("Графики и аналитика", s["body"]))
    story.append(PageBreak())

    for p in ["instagram", "tiktok", "x", "threads"]:
        items = platforms.get(p, [])
        if not items:
            continue
        p_followers = sum(safe_num(stats_by_account.get(a["id"], {}).get("followers")) for a in items)
        p_likes = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_likes")) for a in items)
        p_posts = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_posts")) for a in items)
        p_views = sum(safe_num(stats_by_account.get(a["id"], {}).get("total_views")) for a in items)

        story.append(Paragraph(platform_label(p), s["h1"]))
        story.append(Paragraph(f"{len(items)} аккаунт(ов), с данными: {sum(1 for a in items if stats_by_account.get(a['id'], {}).get('status') == 'ok')}", s["small"]))
        story.append(Spacer(1, 8))
        story.append(metrics_row([
            ("Подписчики", k_format(p_followers)),
            ("Лайки", k_format(p_likes)),
            ("Посты", k_format(p_posts)),
            ("Просмотры", k_format(p_views)),
        ]))
        story.append(Spacer(1, 12))
        story.append(account_table(items, stats_by_account))

        notes = []
        for acc in items:
            st = stats_by_account.get(acc["id"], {})
            if st.get("note"):
                notes.append(f"@{acc.get('username')}: {st.get('note')[:190]}")
        if notes:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Notes / Collector status", s["h2"]))
            for note in notes:
                story.append(Paragraph(note, s["small"]))
        story.append(PageBreak())

    story.append(Paragraph("Сравнение аккаунтов", s["h1"]))
    story.append(account_table(accounts, stats_by_account))
    story.append(Spacer(1, 15))

    follower_chart = bar_chart(
        "Followers by account",
        [f"@{a.get('username')}" for a in accounts],
        [safe_num(stats_by_account.get(a["id"], {}).get("followers")) for a in accounts],
        "followers",
    )
    story.append(Image(follower_chart, width=175*mm, height=75*mm))
    story.append(PageBreak())

    story.append(Paragraph("Графики и аналитика", s["h1"]))
    story.append(Paragraph("Визуальное представление ключевых показателей", s["body"]))
    story.append(Spacer(1, 10))

    by_platform = {}
    for acc in accounts:
        p = acc.get("platform")
        st = stats_by_account.get(acc["id"], {})
        by_platform.setdefault(p, {"followers": 0, "likes": 0, "views": 0, "posts": 0})
        by_platform[p]["followers"] += safe_num(st.get("followers"))
        by_platform[p]["likes"] += safe_num(st.get("total_likes"))
        by_platform[p]["views"] += safe_num(st.get("total_views"))
        by_platform[p]["posts"] += safe_num(st.get("total_posts"))

    labels = [platform_label(p) for p in by_platform.keys()]
    story.append(Image(pie_chart("Followers share by platform", labels, [v["followers"] for v in by_platform.values()]), width=135*mm, height=85*mm))
    story.append(Spacer(1, 6))
    story.append(Image(bar_chart("Likes by platform", labels, [v["likes"] for v in by_platform.values()], "likes"), width=175*mm, height=75*mm))
    story.append(PageBreak())
    story.append(Paragraph("Дополнительные графики", s["h1"]))
    story.append(Image(bar_chart("Views by platform", labels, [v["views"] for v in by_platform.values()], "views"), width=175*mm, height=75*mm))
    story.append(Spacer(1, 8))
    story.append(Image(bar_chart("Posts by platform", labels, [v["posts"] for v in by_platform.values()], "posts"), width=175*mm, height=75*mm))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return str(path)
