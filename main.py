from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from genai_digest.audio import generate_mp3_from_script, render_podcast_script
from genai_digest.config import load_config, load_dotenv
from genai_digest.emailer import send_email
from genai_digest.models import Article
from genai_digest.pdf_report import write_pdf_report
from genai_digest.pipeline import build_digest, canonicalize_url
from genai_digest.report import render_html_report, render_subject, render_text_report
from genai_digest.state import load_article_archive, load_seen_items, save_seen_items
from genai_digest.url_resolver import resolve_article_links


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and send the daily GenAI intelligence report.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "digest_config.json")
    parser.add_argument("--sample", action="store_true", help="Use embedded sample data instead of live web fetches.")
    parser.add_argument("--no-email", action="store_true", help="Generate the report without sending an email.")
    parser.add_argument("--with-audio", action="store_true", help="Generate an MP3 audio brief.")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio generation even if AUDIO_ENABLED=true.")
    return parser.parse_args()


def register_secret_masks(values: list[str]) -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return
    for value in values:
        print(f"::add-mask::{value}")


def validate_email_config(config) -> list[str]:
    issues: list[str] = []
    if config.email.missing_fields:
        issues.append(
            "Missing required settings: " + ", ".join(config.email.missing_fields)
        )
    if config.email.placeholder_fields:
        issues.append(
            "Placeholder values detected for: " + ", ".join(config.email.placeholder_fields)
        )
    return issues


def redact_error_message(message: str, config) -> str:
    redacted = message
    replacements = {
        config.email.from_email: "<redacted:GENAI_REPORT_FROM>",
        config.email.to_email: "<redacted:GENAI_REPORT_TO>",
        config.email.pdf_only_email: "<redacted:GENAI_REPORT_PDF_ONLY_TO>",
        config.email.smtp_username: "<redacted:SMTP_USERNAME>",
        config.email.smtp_password: "<redacted:SMTP_PASSWORD>",
    }
    for raw_value, replacement in replacements.items():
        if raw_value:
            redacted = redacted.replace(raw_value, replacement)
    return redacted


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def digest_seen_keys(digest) -> list[str]:
    seen_keys: set[str] = set()
    for article in digest_articles(digest):
        seen_keys.update(article.seen_keys)
    return sorted(seen_keys)


def digest_articles(digest) -> list[Article]:
    articles = digest.top_articles + [
        article
        for items in digest.grouped_articles.values()
        for article in items
    ]
    unique: dict[str, Article] = {}
    for article in articles:
        unique.setdefault(article.title_fingerprint, article)
    return list(unique.values())


def should_include_weekly_summary(now: datetime) -> bool:
    return now.weekday() == 6


def display_priority_articles(digest) -> list[Article]:
    """Visible articles ordered by prominence, deduped by object identity.

    Ordering matters: the link-resolution budget is spent on the most visible
    sections first (highlights, weekly, top signals, then category lists).
    """
    ordered = (
        digest.highlight_articles[:5]
        + digest.weekly_articles[:8]
        + digest.top_articles[:10]
        + [article for items in digest.grouped_articles.values() for article in items]
    )
    seen: set[int] = set()
    unique: list[Article] = []
    for article in ordered:
        if id(article) in seen:
            continue
        seen.add(id(article))
        unique.append(article)
    return unique


def select_weekly_articles(
    archive: list[Article],
    digest,
    now: datetime,
    limit: int = 12,
) -> list[Article]:
    cutoff = now.astimezone(timezone.utc) - timedelta(days=7)
    candidates = archive + digest_articles(digest)
    unique: dict[str, Article] = {}
    for article in candidates:
        published = article.published_at.astimezone(timezone.utc)
        if published < cutoff:
            continue
        existing = unique.get(article.title_fingerprint)
        if existing is None or (article.score, published) > (
            existing.score,
            existing.published_at.astimezone(timezone.utc),
        ):
            unique[article.title_fingerprint] = article
    return sorted(
        unique.values(),
        key=lambda article: (article.score, article.published_at),
        reverse=True,
    )[:limit]


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    config = load_config(PROJECT_ROOT, args.config)
    register_secret_masks(config.email.masked_values)
    now = datetime.now(ZoneInfo(config.timezone))

    seen_items = {} if args.sample else load_seen_items(config.state_path)
    article_archive = [] if args.sample else load_article_archive(config.state_path)
    digest = build_digest(
        config=config,
        now=now,
        seen_ids=set(seen_items),
        sample_mode=args.sample,
    )
    if should_include_weekly_summary(now):
        digest.weekly_articles = select_weekly_articles(article_archive, digest, now)
    else:
        digest.highlight_articles = select_weekly_articles(article_archive, digest, now, limit=5)

    if env_bool("RESOLVE_LINKS", True):
        display_articles = display_priority_articles(digest)
        resolved_count, failed_count = resolve_article_links(
            display_articles,
            timeout_seconds=config.request_timeout_seconds,
            max_resolutions=env_int("RESOLVE_LINKS_MAX", 50),
        )
        for article in display_articles:
            article.url = canonicalize_url(article.url)
        if failed_count:
            digest.warnings.append(
                f"Link resolution: {resolved_count} resolved, {failed_count} kept as Google News links."
            )

    podcast_script = render_podcast_script(digest, config)
    podcast_script_path = config.reports_dir / f"genai-podcast-script-{now:%Y%m%d}.txt"
    podcast_script_path.write_text(podcast_script, encoding="utf-8")

    audio_enabled = (args.with_audio or env_bool("AUDIO_ENABLED")) and not args.no_audio
    audio_attachments: list[Path] = []
    if audio_enabled:
        audio_path = config.reports_dir / f"genai-audio-brief-{now:%Y%m%d}.mp3"
        try:
            audio_engine = generate_mp3_from_script(
                podcast_script_path,
                audio_path,
                voice=os.environ.get("AUDIO_VOICE", "en-US-AndrewMultilingualNeural"),
                voice_b=os.environ.get("AUDIO_VOICE_B", "en-US-EmmaMultilingualNeural"),
                rate=os.environ.get("AUDIO_RATE", "+0%"),
                speed=env_int("AUDIO_SPEED", 160),
            )
            if not audio_engine.startswith("edge-tts"):
                digest.warnings.append(
                    "Audio used fallback speech engine; install edge-tts for more natural audio."
                )
            audio_attachments.append(audio_path)
        except Exception as exc:
            digest.warnings.append(f"Audio generation failed: {exc}")

    html_report = render_html_report(digest, config)
    text_report = render_text_report(digest, config)
    subject = render_subject(digest.generated_at, config.timezone, weekly=bool(digest.weekly_articles))
    output_name = f"genai-digest-{now:%Y%m%d}.html"
    report_path = config.reports_dir / output_name
    report_path.write_text(html_report, encoding="utf-8")
    pdf_path = config.reports_dir / f"genai-digest-{now:%Y%m%d}.pdf"
    write_pdf_report(digest, config, pdf_path)

    should_send_email = not args.no_email and not args.sample
    if should_send_email:
        issues = validate_email_config(config)
        if issues:
            raise SystemExit(
                "Email configuration is incomplete. "
                + " ".join(issues)
                + " Populate .env or GitHub Actions secrets before sending."
            )
        try:
            full_attachments = [pdf_path, *audio_attachments]
            send_email(
                config.email,
                subject,
                html_report,
                text_report,
                attachments=full_attachments,
            )
            if config.email.pdf_only_email:
                send_email(
                    config.email,
                    subject,
                    html_report,
                    text_report,
                    attachments=[pdf_path],
                    to_email=config.email.pdf_only_email,
                )
        except Exception as exc:
            safe_message = redact_error_message(str(exc), config)
            raise SystemExit(
                "Email delivery failed. Check SMTP settings and credentials. "
                f"Mailer error: {safe_message}"
            ) from None
        save_seen_items(
            config.state_path,
            existing=seen_items,
            item_ids=digest_seen_keys(digest),
            now=now,
            articles=digest_articles(digest),
        )

    print(f"Subject: {subject}")
    print(f"Fresh items: {digest.total_articles}")
    print(f"Report written to: {report_path}")
    print(f"PDF report written to: {pdf_path}")
    print(f"Podcast script written to: {podcast_script_path}")
    if audio_attachments:
        print(f"Audio brief written to: {audio_attachments[0]}")
    if should_send_email:
        delivery_mode = "full and PDF-only emails sent" if config.email.pdf_only_email else "sent"
        print(f"Email delivery: {delivery_mode}")
    elif args.sample:
        print("Email delivery: skipped in sample mode")
    else:
        print("Email delivery: skipped by flag")
    if digest.warnings:
        print("Warnings:")
        for warning in digest.warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
