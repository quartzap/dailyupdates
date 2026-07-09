from __future__ import annotations

import json
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
DISCORD_API_ENDPOINT = "https://discord.com/api/v10"
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


def fetch_json(url: str, timeout_seconds: int, headers: dict[str, str] | None = None) -> dict | list:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


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


def parse_atom_feed(
    xml_text: str,
    category: str,
    fallback_source: str = "Atom",
    source_type: str = "news",
) -> list[Article]:
    root = ElementTree.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    articles: list[Article] = []
    for entry in root.findall(".//atom:entry", ns):
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        link = ""
        for link_node in entry.findall("atom:link", ns):
            link = link_node.attrib.get("href", "")
            if link:
                break
        summary = clean_text(
            entry.findtext("atom:summary", default="", namespaces=ns)
            or entry.findtext("atom:content", default="", namespaces=ns)
        )
        published = (
            parse_datetime(entry.findtext("atom:published", default="", namespaces=ns))
            or parse_datetime(entry.findtext("atom:updated", default="", namespaces=ns))
            or datetime.now(timezone.utc)
        )
        if not title or not link:
            continue
        articles.append(
            Article(
                title=title,
                url=link,
                source=fallback_source,
                published_at=published,
                summary=summary,
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


def fetch_reddit_social(category: CategoryConfig, config: AppConfig) -> list[Article]:
    query = social_query_for_category(category)
    rss_url = "https://www.reddit.com/search.rss?" + urlencode(
        {
            "q": query,
            "sort": "new",
            "t": "day",
        }
    )
    xml_text = fetch_url(rss_url, config.request_timeout_seconds)
    articles = parse_atom_feed(
        xml_text,
        category.key,
        fallback_source="Reddit",
        source_type="reddit",
    )
    return articles[: config.social.max_items_per_category]


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


def fetch_discord_social(config: AppConfig) -> list[Article]:
    token = config.social.discord_bot_token
    channel_ids = config.social.discord_channel_ids
    if not token or not channel_ids:
        return []

    headers = {"Authorization": f"Bot {token}"}
    articles: list[Article] = []
    for channel_id in channel_ids:
        channel = fetch_json(
            f"{DISCORD_API_ENDPOINT}/channels/{channel_id}",
            config.request_timeout_seconds,
            headers=headers,
        )
        messages = fetch_json(
            f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/messages?limit=50",
            config.request_timeout_seconds,
            headers=headers,
        )
        if not isinstance(messages, list):
            continue
        guild_id = channel.get("guild_id") if isinstance(channel, dict) else None
        channel_name = channel.get("name", channel_id) if isinstance(channel, dict) else channel_id
        for message in messages:
            article = discord_message_to_article(message, str(channel_id), str(channel_name), guild_id, config)
            if article is not None:
                articles.append(article)
    return articles


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


def discord_message_to_article(
    message: dict,
    channel_id: str,
    channel_name: str,
    guild_id: str | None,
    config: AppConfig,
) -> Article | None:
    content = clean_text(message.get("content", ""))
    if not content:
        return None
    matched_categories = categories_for_text(content, config)
    if not matched_categories:
        return None
    author = message.get("author", {}) if isinstance(message.get("author"), dict) else {}
    author_name = author.get("global_name") or author.get("username") or "Discord"
    message_id = message.get("id")
    published = parse_datetime(message.get("timestamp")) or datetime.now(timezone.utc)
    target_guild_id = guild_id or "@me"
    url = f"https://discord.com/channels/{target_guild_id}/{channel_id}/{message_id}"
    title = summarize_discord_title(content, author_name)
    return Article(
        title=title,
        url=url,
        source=f"Discord #{channel_name}",
        published_at=published,
        summary=content,
        categories=matched_categories,
        source_type="discord",
    )


def categories_for_text(text: str, config: AppConfig) -> set[str]:
    haystack = text.lower()
    matched: set[str] = set()
    for category in config.categories:
        if any(keyword.lower() in haystack for keyword in category.keywords):
            matched.add(category.key)
    return matched


def summarize_discord_title(content: str, author_name: str, max_chars: int = 120) -> str:
    compacted = " ".join(content.split())
    if len(compacted) > max_chars:
        compacted = compacted[:max_chars].rsplit(" ", 1)[0] + "..."
    return f"{author_name}: {compacted}"
