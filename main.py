from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from genai_digest.config import load_config, load_dotenv
from genai_digest.emailer import send_email
from genai_digest.pipeline import build_digest
from genai_digest.report import render_html_report, render_subject, render_text_report
from genai_digest.state import load_seen_items, save_seen_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and send the daily GenAI intelligence report.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "digest_config.json")
    parser.add_argument("--sample", action="store_true", help="Use embedded sample data instead of live web fetches.")
    parser.add_argument("--no-email", action="store_true", help="Generate the report without sending an email.")
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
        config.email.smtp_username: "<redacted:SMTP_USERNAME>",
        config.email.smtp_password: "<redacted:SMTP_PASSWORD>",
    }
    for raw_value, replacement in replacements.items():
        if raw_value:
            redacted = redacted.replace(raw_value, replacement)
    return redacted


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    config = load_config(PROJECT_ROOT, args.config)
    register_secret_masks(config.email.masked_values)
    now = datetime.now(ZoneInfo(config.timezone))

    seen_items = {} if args.sample else load_seen_items(config.state_path)
    digest = build_digest(
        config=config,
        now=now,
        seen_ids=set(seen_items),
        sample_mode=args.sample,
    )

    html_report = render_html_report(digest, config)
    text_report = render_text_report(digest, config)
    subject = render_subject(digest.generated_at, config.timezone)
    output_name = f"genai-digest-{now:%Y%m%d}.html"
    report_path = config.reports_dir / output_name
    report_path.write_text(html_report, encoding="utf-8")

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
            send_email(config.email, subject, html_report, text_report)
        except Exception as exc:
            safe_message = redact_error_message(str(exc), config)
            raise SystemExit(
                "Email delivery failed. Check SMTP settings and credentials. "
                f"Mailer error: {safe_message}"
            ) from None
        save_seen_items(
            config.state_path,
            existing=seen_items,
            item_ids=[article.id for article in digest.top_articles] + [
                article.id
                for items in digest.grouped_articles.values()
                for article in items
            ],
            now=now,
        )

    print(f"Subject: {subject}")
    print(f"Fresh items: {digest.total_articles}")
    print(f"Report written to: {report_path}")
    if should_send_email:
        print("Email delivery: sent")
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
