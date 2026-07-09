from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .models import Article


def load_seen_items(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("sent", {})


def load_article_archive(path: Path) -> list[Article]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    articles: list[Article] = []
    for record in raw.get("articles", {}).values():
        try:
            articles.append(article_from_record(record))
        except (KeyError, TypeError, ValueError):
            continue
    return articles


def save_seen_items(
    path: Path,
    existing: dict[str, str],
    item_ids: list[str],
    now: datetime,
    articles: list[Article] | None = None,
) -> None:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    pruned = prune_seen_items(existing, now, retention_days=21)
    for item_id in item_ids:
        pruned[item_id] = now.isoformat()
    archived_articles = prune_article_archive(raw.get("articles", {}), now, retention_days=35)
    for article in articles or []:
        archived_articles[article.id] = article_to_record(article)
    payload = {
        "last_updated": now.isoformat(),
        "sent": pruned,
        "articles": archived_articles,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def prune_seen_items(seen: dict[str, str], now: datetime, retention_days: int) -> dict[str, str]:
    cutoff = now - timedelta(days=retention_days)
    kept: dict[str, str] = {}
    for key, raw_timestamp in seen.items():
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            continue
        if timestamp >= cutoff:
            kept[key] = raw_timestamp
    return kept


def prune_article_archive(articles: dict[str, dict], now: datetime, retention_days: int) -> dict[str, dict]:
    cutoff = now - timedelta(days=retention_days)
    kept: dict[str, dict] = {}
    for key, record in articles.items():
        try:
            timestamp = datetime.fromisoformat(record["published_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp >= cutoff:
            kept[key] = record
    return kept


def article_to_record(article: Article) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at.isoformat(),
        "summary": article.summary,
        "categories": sorted(article.categories),
        "source_type": article.source_type,
        "score": article.score,
    }


def article_from_record(record: dict) -> Article:
    return Article(
        title=record["title"],
        url=record["url"],
        source=record["source"],
        published_at=datetime.fromisoformat(record["published_at"]),
        summary=record.get("summary", ""),
        categories=set(record.get("categories", [])),
        source_type=record.get("source_type", "news"),
        score=float(record.get("score", 0.0)),
    )
