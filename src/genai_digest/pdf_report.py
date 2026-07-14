from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .config import AppConfig
from .models import Article, DigestResult
from .report import render_subject


def write_pdf_report(digest: DigestResult, config: AppConfig, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.55 * inch,
        title=render_subject(digest.generated_at, config.timezone, weekly=bool(digest.weekly_articles)),
    )

    weekly_articles = digest.weekly_articles[:8]
    weekly_article_ids = {article.title_fingerprint for article in weekly_articles}
    highlight_articles = [] if weekly_articles else digest.highlight_articles[:5]
    highlight_ids = {article.title_fingerprint for article in highlight_articles}
    top_articles = [
        article
        for article in digest.top_articles
        if article.title_fingerprint not in weekly_article_ids and article.title_fingerprint not in highlight_ids
    ][:5]
    top_article_ids = {article.title_fingerprint for article in top_articles}

    story: list = []
    generated_local = digest.generated_at.astimezone(ZoneInfo(config.timezone))
    title = "Weekly GenAI Intelligence Brief" if weekly_articles else "Daily GenAI Intelligence Brief"
    story.append(Paragraph(xml_escape(title), styles["DigestTitle"]))
    story.append(
        Paragraph(
            xml_escape(
                f"Generated {generated_local:%d %b %Y %I:%M %p %Z}. "
                f"{digest.total_articles} fresh items found in today's scan."
            ),
            styles["Meta"],
        )
    )
    story.append(Spacer(1, 0.18 * inch))

    if highlight_articles:
        add_section(
            story,
            "Week Highlights",
            f"Top {len(highlight_articles)} updates from the last 7 days.",
            highlight_articles,
            config.timezone,
            styles,
        )

    if weekly_articles:
        add_section(
            story,
            "Weekly Major Updates",
            f"{len(weekly_articles)} notable updates from the last 7 days.",
            weekly_articles,
            config.timezone,
            styles,
        )

    add_section(
        story,
        "Top Signals",
        f"{len(top_articles)} updates from today's scan.",
        top_articles,
        config.timezone,
        styles,
        empty_text="No top signals available.",
    )

    for category_key, label in config.category_labels.items():
        articles = [
            article
            for article in digest.grouped_articles.get(category_key, [])
            if article.title_fingerprint not in top_article_ids
            and article.title_fingerprint not in weekly_article_ids
            and article.title_fingerprint not in highlight_ids
        ]
        add_section(
            story,
            label,
            f"{len(articles)} updates",
            articles,
            config.timezone,
            styles,
            empty_text="No new items found in this window.",
        )


    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return output_path


def build_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "DigestTitle": ParagraphStyle(
            "DigestTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#062b55"),
            spaceAfter=8,
        ),
        "SectionTitle": ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#17202a"),
            spaceBefore=12,
            spaceAfter=4,
        ),
        "SectionMeta": ParagraphStyle(
            "SectionMeta",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#607080"),
            spaceAfter=7,
        ),
        "Article": ParagraphStyle(
            "Article",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            spaceAfter=8,
        ),
        "Meta": ParagraphStyle(
            "Meta",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#51606f"),
        ),
        "Empty": ParagraphStyle(
            "Empty",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#607080"),
            spaceAfter=8,
        ),
    }


def add_section(
    story: list,
    title: str,
    subtitle: str,
    articles: list[Article],
    timezone_name: str,
    styles: dict[str, ParagraphStyle],
    empty_text: str = "No updates available.",
) -> None:
    story.append(Paragraph(xml_escape(title), styles["SectionTitle"]))
    story.append(Paragraph(xml_escape(subtitle), styles["SectionMeta"]))
    if not articles:
        story.append(Paragraph(xml_escape(empty_text), styles["Empty"]))
        return
    for article in articles:
        story.append(render_article_pdf(article, timezone_name, styles["Article"]))


def render_article_pdf(article: Article, timezone_name: str, style: ParagraphStyle) -> Paragraph:
    published_local = article.published_at.astimezone(ZoneInfo(timezone_name))
    categories = ", ".join(sorted(article.categories)).replace("_", " ").title()
    title = xml_escape(article.title)
    href = xml_escape(article.url, {'"': "&quot;"})
    meta = xml_escape(f"{article.source} | {published_local:%d %b %Y %I:%M %p %Z} | {categories}")
    return Paragraph(
        f'<a href="{href}"><font color="#0d5ea6"><b>{title}</b></font></a><br/>'
        f'<font size="8" color="#607080">{meta}</font>',
        style,
    )


def draw_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#607080"))
    canvas.drawString(0.6 * inch, 0.32 * inch, "Generated by GenAI Daily Report Utility")
    canvas.drawRightString(A4[0] - 0.6 * inch, 0.32 * inch, f"Page {doc.page}")
    canvas.restoreState()
