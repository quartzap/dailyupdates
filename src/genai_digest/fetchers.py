from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .config import AppConfig, CategoryConfig, RssFeedConfig, build_google_news_rss_url
from .models import Article

USER_AGENT = "genai-daily-digest/1.0 (+https://github.com/)"
ARXIV_API_ENDPOINT = "https://export.arxiv.org/api/query"
HTML_TAG_RE = re.compile(r"<[^>]+>")
SOCIAL_BASE_TERMS = '("generative AI" OR GenAI OR LLM OR "AI agent")'


def fetch_url(url: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 5 * (attempt + 1)
            time.sleep(delay_seconds)
    raise RuntimeError(f"Unable to fetch {url}")


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


def parse_rss_feed(
    xml_text: str,
    category: str,
    fallback_source: str = "RSS",
    source_type: str = "news",
) -> list[Article]:
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
                source_type=source_type,
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


def fetch_x_social(category: CategoryConfig, config: AppConfig) -> list[Article]:
    # X does not expose a stable free trending-search API. This uses public news/search
    # indexing around x.com/twitter.com as a low-cost signal source.
    query = f"({social_query_for_category(category)}) (site:x.com OR site:twitter.com)"
    rss_url = build_google_news_rss_url(query)
    xml_text = fetch_url(rss_url, config.request_timeout_seconds)
    articles = parse_rss_feed(
        xml_text,
        category.key,
        fallback_source="X Search",
        source_type="x",
    )
    return articles[: config.social.max_items_per_category]


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


def social_query_for_category(category: CategoryConfig) -> str:
    keywords = category.keywords[:8]
    if not keywords:
        return SOCIAL_BASE_TERMS
    keyword_query = " OR ".join(quote_search_term(keyword) for keyword in keywords)
    return f"{SOCIAL_BASE_TERMS} ({keyword_query})"


def quote_search_term(term: str) -> str:
    stripped = term.strip()
    if not stripped:
        return stripped
    if " " in stripped and not (stripped.startswith('"') and stripped.endswith('"')):
        return f'"{stripped}"'
    return stripped
