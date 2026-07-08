from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .config import AppConfig, CategoryConfig, RssFeedConfig, build_google_news_rss_url
from .models import Article

USER_AGENT = "genai-daily-digest/1.0 (+https://github.com/)"
ARXIV_API_ENDPOINT = "https://export.arxiv.org/api/query"
HTML_TAG_RE = re.compile(r"<[^>]+>")


def fetch_url(url: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    no_tags = HTML_TAG_RE.sub(" ", value or "")
    normalized = " ".join(unescape(no_tags).split())
    return normalized.strip()


def parse_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        parsed = parsedate_to_datetime(raw_value)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        normalized = raw_value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_rss_feed(xml_text: str, category: str, fallback_source: str = "RSS") -> list[Article]:
    root = ElementTree.fromstring(xml_text)
    items = root.findall(".//item")
    articles: list[Article] = []
    for item in items:
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        description = clean_text(item.findtext("description"))
        source_node = item.find("source")
        source = clean_text(source_node.text if source_node is not None else "") or fallback_source
        published = parse_datetime(item.findtext("pubDate")) or datetime.now(timezone.utc)
        if not title or not link:
            continue
        articles.append(
            Article(
                title=title,
                url=link,
                source=source,
                published_at=published,
                summary=description,
                categories={category},
                source_type="news",
            )
        )
    return articles


def fetch_google_news(category: CategoryConfig, config: AppConfig) -> list[Article]:
    rss_url = build_google_news_rss_url(category.google_news_query)
    xml_text = fetch_url(rss_url, config.request_timeout_seconds)
    return parse_rss_feed(xml_text, category.key, fallback_source="Google News")


def fetch_generic_rss(feed: RssFeedConfig, config: AppConfig) -> list[Article]:
    xml_text = fetch_url(feed.url, config.request_timeout_seconds)
    return parse_rss_feed(xml_text, feed.category, fallback_source=feed.label)


def fetch_arxiv(config: AppConfig) -> list[Article]:
    params = urlencode(
        {
            "search_query": config.arxiv.search_query,
            "start": 0,
            "max_results": config.arxiv.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    xml_text = fetch_url(f"{ARXIV_API_ENDPOINT}?{params}", config.request_timeout_seconds)
    root = ElementTree.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    articles: list[Article] = []
    for entry in root.findall("atom:entry", ns):
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        link = ""
        for link_node in entry.findall("atom:link", ns):
            if link_node.attrib.get("rel") == "alternate":
                link = link_node.attrib.get("href", "")
                break
        summary = clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        published = parse_datetime(entry.findtext("atom:published", default="", namespaces=ns))
        if not title or not link or published is None:
            continue
        articles.append(
            Article(
                title=title,
                url=link,
                source="arXiv",
                published_at=published,
                summary=summary,
                categories={config.arxiv.category},
                source_type="paper",
            )
        )
    return articles

