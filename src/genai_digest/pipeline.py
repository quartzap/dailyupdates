from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from .config import AppConfig
from .fetchers import fetch_arxiv, fetch_generic_rss, fetch_google_news
from .models import Article, DigestResult
from .sample_data import build_sample_articles


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    sanitized_query = "&".join(
        part
        for part in parts.query.split("&")
        if part and not part.startswith("utm_")
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, sanitized_query, ""))


def enrich_categories(article: Article, config: AppConfig) -> None:
    haystack = f"{article.title} {article.summary}".lower()
    for category in config.categories:
        if any(keyword.lower() in haystack for keyword in category.keywords):
            article.categories.add(category.key)


def score_article(article: Article, now: datetime) -> float:
    age_hours = max((now - article.published_at).total_seconds() / 3600.0, 0.0)
    base_score = max(0.0, 96.0 - age_hours)
    category_bonus = len(article.categories) * 3.0
    source_bonus = 5.0 if article.source_type == "paper" else 0.0
    return round(base_score + category_bonus + source_bonus, 2)


def collect_articles(config: AppConfig, now: datetime, sample_mode: bool = False) -> tuple[list[Article], list[str]]:
    if sample_mode:
        articles = build_sample_articles(now.astimezone(timezone.utc))
        return articles, []

    warnings: list[str] = []
    collected: list[Article] = []

    for category in config.categories:
        try:
            collected.extend(fetch_google_news(category, config))
        except Exception as exc:
            warnings.append(f"Google News fetch failed for {category.label}: {exc}")

    for feed in config.rss_feeds:
        try:
            collected.extend(fetch_generic_rss(feed, config))
        except Exception as exc:
            warnings.append(f"RSS fetch failed for {feed.label}: {exc}")

    try:
        collected.extend(fetch_arxiv(config))
    except Exception as exc:
        warnings.append(f"arXiv fetch failed: {exc}")

    return collected, warnings


def build_digest(
    config: AppConfig,
    now: datetime,
    seen_ids: set[str] | None = None,
    sample_mode: bool = False,
) -> DigestResult:
    seen_ids = seen_ids or set()
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=config.lookback_hours)
    raw_articles, warnings = collect_articles(config, now, sample_mode=sample_mode)

    deduped: dict[str, Article] = {}
    for article in raw_articles:
        article.url = canonicalize_url(article.url)
        article.published_at = article.published_at.astimezone(timezone.utc)
        if article.published_at < cutoff:
            continue
        enrich_categories(article, config)
        if not article.categories:
            continue
        article.score = score_article(article, now.astimezone(timezone.utc))
        if article.id in seen_ids:
            continue
        existing = deduped.get(article.id)
        if existing is None or article.score > existing.score:
            deduped[article.id] = article

    sorted_articles = sorted(
        deduped.values(),
        key=lambda item: (item.score, item.published_at),
        reverse=True,
    )

    grouped: dict[str, list[Article]] = defaultdict(list)
    for article in sorted_articles:
        for category_key in sorted(article.categories):
            if category_key not in config.category_labels:
                continue
            if len(grouped[category_key]) >= config.max_items_per_category:
                continue
            grouped[category_key].append(article)

    top_articles = sorted_articles[: min(10, len(sorted_articles))]
    return DigestResult(
        generated_at=now,
        grouped_articles={key: grouped.get(key, []) for key in config.category_labels},
        top_articles=top_articles,
        total_articles=len(sorted_articles),
        warnings=warnings,
    )

