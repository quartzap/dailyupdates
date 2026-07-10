from __future__ import annotations

import base64
import json
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .models import Article

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
GOOGLE_NEWS_HOST_SUFFIX = "news.google.com"
BATCHEXECUTE_ENDPOINT = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
ARTICLE_ID_RE = re.compile(r"/(?:rss/articles|articles|read)/([^/?#]+)")
EMBEDDED_URL_RE = re.compile(rb"https?://[\x20-\x7e]+")
SIGNATURE_RE = re.compile(r'data-n-a-sg="([^"]+)"')
TIMESTAMP_RE = re.compile(r'data-n-a-ts="([^"]+)"')


def is_google_news_url(url: str) -> bool:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return host == GOOGLE_NEWS_HOST_SUFFIX or host.endswith("." + GOOGLE_NEWS_HOST_SUFFIX)


def resolve_article_links(
    articles: list[Article],
    timeout_seconds: int = 10,
    max_resolutions: int = 50,
) -> tuple[int, int]:
    """Resolve Google News redirect URLs in-place to publisher URLs.

    Returns (resolved_count, failed_count). Failures keep the original URL so
    the digest always ships. Articles are processed in the given order, so pass
    the most visible articles first when applying the resolution budget.
    """
    cache: dict[str, str | None] = {}
    resolved = 0
    failed = 0
    attempts = 0
    for article in articles:
        if not is_google_news_url(article.url):
            continue
        if article.url in cache:
            outcome = cache[article.url]
        else:
            if attempts >= max_resolutions:
                continue
            attempts += 1
            outcome = _resolve_single(article.url, timeout_seconds)
            cache[article.url] = outcome
        if outcome:
            article.url = outcome
            resolved += 1
        else:
            failed += 1
    return resolved, failed


def _resolve_single(url: str, timeout_seconds: int) -> str | None:
    article_id_match = ARTICLE_ID_RE.search(urlsplit(url).path)
    article_id = article_id_match.group(1) if article_id_match else None

    # 1. Legacy article IDs are base64-wrapped publisher URLs; zero HTTP calls.
    if article_id:
        decoded = _decode_legacy_id(article_id)
        if decoded:
            return decoded

    # 2. Fetch the article page once: either it redirects off Google, or the
    #    page body carries the signature/timestamp needed for the decode call.
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            body = response.read(400_000).decode("utf-8", errors="replace")
    except Exception:
        return None
    if not is_google_news_url(final_url):
        return final_url

    # 3. New-format IDs: ask Google's own decoding endpoint (the approach used
    #    by the googlenewsdecoder project). May break if Google changes the
    #    internal API, in which case we quietly keep the original link.
    if not article_id:
        return None
    signature_match = SIGNATURE_RE.search(body)
    timestamp_match = TIMESTAMP_RE.search(body)
    if not signature_match or not timestamp_match:
        return None
    return _resolve_via_batchexecute(
        article_id, signature_match.group(1), timestamp_match.group(1), timeout_seconds
    )


def _decode_legacy_id(article_id: str) -> str | None:
    try:
        padded = article_id + "=" * (-len(article_id) % 4)
        decoded = base64.urlsafe_b64decode(padded)
    except (ValueError, TypeError):
        return None
    matches = EMBEDDED_URL_RE.findall(decoded)
    for match in matches:
        candidate = match.decode("ascii", errors="ignore")
        # Trim protobuf length/tag bytes that can trail the URL.
        candidate = re.split(r"[\x00-\x1f]", candidate)[0].rstrip("\\")
        if candidate.startswith(("http://", "https://")) and not is_google_news_url(candidate):
            return candidate
    return None


def _resolve_via_batchexecute(
    article_id: str, signature: str, timestamp: str, timeout_seconds: int
) -> str | None:
    inner_request = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            "null,null,null,null,null,0,1],"
            '"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{article_id}",{timestamp},"{signature}"]'
        ),
    ]
    form_body = "f.req=" + quote(json.dumps([[inner_request]]))
    request = Request(
        BATCHEXECUTE_ENDPOINT,
        data=form_body.encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
        chunk = raw.split("\n\n")[1]
        outer = json.loads(chunk)
        inner = json.loads(outer[0][2])
        resolved = inner[1]
    except Exception:
        return None
    if isinstance(resolved, str) and resolved.startswith(("http://", "https://")):
        return resolved
    return None
