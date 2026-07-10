from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .config import AppConfig
from .models import Article, DigestResult


def render_subject(generated_at: datetime, timezone_name: str, weekly: bool = False) -> str:
    local_time = generated_at.astimezone(ZoneInfo(timezone_name))
    edition = "Weekly GenAI Intelligence Brief" if weekly else "Daily GenAI Intelligence Brief"
    return f"{edition} | {local_time:%Y-%m-%d}"


def render_article_html(article: Article, timezone_name: str) -> str:
    published_local = article.published_at.astimezone(ZoneInfo(timezone_name))
    categories = ", ".join(sorted(article.categories)).replace("_", " ").title()
    return f"""
    <div class="item">
      <a class="headline" href="{escape(article.url)}">{escape(article.title)}</a>
      <div class="meta">{escape(article.source)} | {published_local:%d %b %Y %I:%M %p %Z} | {escape(categories)}</div>
    </div>
    """


def render_article_text(article: Article, timezone_name: str) -> str:
    published_local = article.published_at.astimezone(ZoneInfo(timezone_name))
    return (
        f"- {article.title}\n"
        f"  Source: {article.source} | {published_local:%Y-%m-%d %H:%M %Z}\n"
        f"  Details: {article.url}\n"
    )


def render_html_report(digest: DigestResult, config: AppConfig) -> str:
    category_blocks: list[str] = []
    labels = config.category_labels
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
    for category_key, label in labels.items():
        articles = [
            article
            for article in digest.grouped_articles.get(category_key, [])
            if article.title_fingerprint not in top_article_ids
            and article.title_fingerprint not in weekly_article_ids
            and article.title_fingerprint not in highlight_ids
        ]
        items = "".join(render_article_html(article, config.timezone) for article in articles)
        empty_state = "<p class='empty'>No new items found in this window.</p>" if not articles else ""
        category_blocks.append(
            f"""
            <section class="card">
              <h2>{escape(label)}</h2>
              <p class="count">{len(articles)} updates</p>
              {items}
              {empty_state}
            </section>
            """
        )

    warning_block = ""
    if digest.warnings:
        warnings_html = "".join(f"<li>{escape(item)}</li>" for item in digest.warnings)
        warning_block = f"""
        <section class="card warnings">
          <h2>Source Warnings</h2>
          <ul>{warnings_html}</ul>
        </section>
        """

    weekly_block = ""
    if weekly_articles:
        weekly_items = "".join(render_article_html(article, config.timezone) for article in weekly_articles)
        weekly_block = f"""
        <section class="card weekly" style="margin-top: 20px;">
          <h2>Weekly Major Updates</h2>
          <p class="count">{len(weekly_articles)} updates from the last 7 days</p>
          {weekly_items}
        </section>
        """

    highlights_block = ""
    if highlight_articles:
        highlight_items = "".join(
            render_article_html(article, config.timezone) for article in highlight_articles
        )
        highlights_block = f"""
        <section class="card highlights" style="margin-top: 20px;">
          <h2>&#128204; Week Highlights</h2>
          <p class="count">Top {len(highlight_articles)} updates from the last 7 days</p>
          {highlight_items}
        </section>
        """

    subject = render_subject(digest.generated_at, config.timezone, weekly=bool(weekly_articles))
    generated_local = digest.generated_at.astimezone(ZoneInfo(config.timezone))
    top_items = "".join(render_article_html(article, config.timezone) for article in top_articles)
    hero_line = f"{digest.total_articles} fresh items. Open a headline for the source details."
    if weekly_articles:
        hero_line = (
            f"Weekly edition with {len(weekly_articles)} major updates from the last 7 days "
            f"and {digest.total_articles} fresh items from today's scan."
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(subject)}</title>
    <style>
      body {{
        margin: 0;
        padding: 24px;
        font-family: Arial, Helvetica, sans-serif;
        background: #f3f6fb;
        color: #17202a;
      }}
      .container {{
        max-width: 1080px;
        margin: 0 auto;
      }}
      .hero {{
        background: linear-gradient(135deg, #062b55 0%, #0d5ea6 65%, #6ab7ff 100%);
        color: white;
        border-radius: 18px;
        padding: 28px;
        box-shadow: 0 18px 36px rgba(6, 43, 85, 0.18);
      }}
      .hero h1 {{
        margin: 0 0 8px 0;
        font-size: 30px;
      }}
      .hero p {{
        margin: 6px 0;
        line-height: 1.5;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
        gap: 18px;
        margin-top: 20px;
      }}
      .card {{
        background: white;
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 14px 30px rgba(18, 38, 63, 0.08);
      }}
      .card h2 {{
        margin-top: 0;
        margin-bottom: 8px;
        font-size: 20px;
      }}
      .count {{
        margin: 0 0 14px 0;
        color: #51606f;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      .item {{
        padding: 10px 0;
        border-top: 1px solid #e8eef5;
      }}
      .item:first-of-type {{
        border-top: none;
        padding-top: 0;
      }}
      .headline {{
        color: #0d5ea6;
        font-weight: bold;
        text-decoration: none;
      }}
      .meta {{
        margin-top: 6px;
        color: #607080;
        font-size: 12px;
      }}
      .empty {{
        color: #607080;
        margin-bottom: 0;
      }}
      .warnings ul {{
        margin-bottom: 0;
      }}
      .weekly {{
        border: 1px solid #d8e8f8;
      }}
      .highlights {{
        border: 2px solid #0d5ea6;
        background: #f4f9ff;
      }}
      @media (max-width: 700px) {{
        body {{
          padding: 14px;
        }}
        .hero {{
          padding: 20px;
        }}
        .hero h1 {{
          font-size: 24px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <section class="hero">
        <h1>{escape("Weekly GenAI Intelligence Brief" if weekly_articles else "Daily GenAI Intelligence Brief")}</h1>
        <p>{escape(hero_line)}</p>
        <p>Generated at {generated_local:%d %b %Y %I:%M %p %Z}.</p>
      </section>
      {highlights_block}
      {weekly_block}
      <section class="card" style="margin-top: 20px;">
        <h2>Top Signals</h2>
        <p class="count">{len(top_articles)} updates</p>
        {top_items or "<p class='empty'>No top signals available.</p>"}
      </section>
      <div class="grid">
        {''.join(category_blocks)}
      </div>
      {warning_block}
    </div>
  </body>
</html>
"""


def render_text_report(digest: DigestResult, config: AppConfig) -> str:
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
    lines = [
        render_subject(digest.generated_at, config.timezone, weekly=bool(weekly_articles)),
        "",
    ]
    lines.append(f"Fresh items: {digest.total_articles}")
    lines.append("")

    if highlight_articles:
        lines.append("Week Highlights")
        lines.append("---------------")
        for article in highlight_articles:
            lines.append(render_article_text(article, config.timezone))
        lines.append("")

    if weekly_articles:
        lines.append("Weekly Major Updates")
        lines.append("--------------------")
        for article in weekly_articles:
            lines.append(render_article_text(article, config.timezone))
        lines.append("")

    if top_articles:
        lines.append("Top Signals")
        lines.append("-----------")
        for article in top_articles:
            lines.append(render_article_text(article, config.timezone))
        lines.append("")
    for category_key, label in config.category_labels.items():
        lines.append(label)
        lines.append("-" * len(label))
        articles = [
            article
            for article in digest.grouped_articles.get(category_key, [])
            if article.title_fingerprint not in top_article_ids
            and article.title_fingerprint not in weekly_article_ids
            and article.title_fingerprint not in highlight_ids
        ]
        if not articles:
            lines.append("No new items found in this window.")
        else:
            for article in articles:
                lines.append(render_article_text(article, config.timezone))
        lines.append("")

    if digest.warnings:
        lines.append("Source Warnings")
        lines.append("---------------")
        lines.extend(f"- {warning}" for warning in digest.warnings)
        lines.append("")

    return "\n".join(lines).strip() + "\n"
