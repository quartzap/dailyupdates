from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode


@dataclass(slots=True)
class CategoryConfig:
    key: str
    label: str
    google_news_query: str
    keywords: list[str]


@dataclass(slots=True)
class RssFeedConfig:
    label: str
    category: str
    url: str


@dataclass(slots=True)
class ArxivConfig:
    category: str
    search_query: str
    max_results: int


@dataclass(slots=True)
class EmailConfig:
    from_email: str | None
    to_email: str | None
    pdf_only_email: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_use_tls: bool

    @property
    def is_ready(self) -> bool:
        return not self.missing_fields

    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.from_email:
            missing.append("GENAI_REPORT_FROM")
        if not self.to_email:
            missing.append("GENAI_REPORT_TO")
        if not self.smtp_host:
            missing.append("SMTP_HOST")
        if not self.smtp_username:
            missing.append("SMTP_USERNAME")
        if not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        return missing

    @property
    def placeholder_fields(self) -> list[str]:
        placeholder_values = {
            "GENAI_REPORT_FROM": {"your-email@gmail.com", "example@example.com"},
            "GENAI_REPORT_TO": {"your-email@gmail.com", "example@example.com"},
            "GENAI_REPORT_PDF_ONLY_TO": {"your-email@gmail.com", "example@example.com"},
            "SMTP_USERNAME": {"your-email@gmail.com", "example@example.com"},
            "SMTP_PASSWORD": {"your-app-password", "changeme", "example-password"},
        }
        field_values = {
            "GENAI_REPORT_FROM": self.from_email,
            "GENAI_REPORT_TO": self.to_email,
            "GENAI_REPORT_PDF_ONLY_TO": self.pdf_only_email,
            "SMTP_USERNAME": self.smtp_username,
            "SMTP_PASSWORD": self.smtp_password,
        }
        placeholders: list[str] = []
        for field_name, value in field_values.items():
            if value and value.lower() in placeholder_values.get(field_name, set()):
                placeholders.append(field_name)
        return placeholders

    @property
    def masked_values(self) -> list[str]:
        values = [
            self.from_email,
            self.to_email,
            self.pdf_only_email,
            self.smtp_username,
            self.smtp_password,
        ]
        return [value for value in values if value]


@dataclass(slots=True)
class SocialConfig:
    platforms: set[str]
    max_items_per_category: int


@dataclass(slots=True)
class AppConfig:
    timezone: str
    lookback_hours: int
    max_items_per_category: int
    categories: list[CategoryConfig]
    rss_feeds: list[RssFeedConfig]
    arxiv: ArxivConfig
    email: EmailConfig
    reports_dir: Path
    state_path: Path
    request_timeout_seconds: int
    social: SocialConfig

    @property
    def category_labels(self) -> dict[str, str]:
        return {category.key: category.label for category in self.categories}


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_value(env: dict[str, str], key: str, default: str | None = None) -> str | None:
    value = env.get(key)
    if value is None:
        return default
    stripped = value.strip()
    return stripped if stripped else default


def env_int(env: dict[str, str], key: str, default: int) -> int:
    value = env_value(env, key)
    if value is None:
        return default
    return int(value)


def env_csv(env: dict[str, str], key: str, default: list[str]) -> list[str]:
    raw_value = env_value(env, key)
    if raw_value is None:
        return default
    return [item.strip() for item in raw_value.replace("\n", ",").split(",") if item.strip()]


def build_google_news_rss_url(query: str) -> str:
    params = urlencode(
        {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    return f"https://news.google.com/rss/search?{params}"


def load_config(project_root: Path, config_path: Path | None = None) -> AppConfig:
    resolved_config_path = config_path or project_root / "digest_config.json"
    raw = json.loads(resolved_config_path.read_text(encoding="utf-8"))

    categories = [
        CategoryConfig(
            key=item["key"],
            label=item["label"],
            google_news_query=item["google_news_query"],
            keywords=item.get("keywords", []),
        )
        for item in raw["categories"]
    ]
    rss_feeds = [
        RssFeedConfig(
            label=item["label"],
            category=item["category"],
            url=item["url"],
        )
        for item in raw.get("rss_feeds", [])
    ]
    arxiv_cfg = raw["arxiv"]
    arxiv = ArxivConfig(
        category=arxiv_cfg["category"],
        search_query=arxiv_cfg["search_query"],
        max_results=int(arxiv_cfg.get("max_results", 12)),
    )

    env = os.environ
    email = EmailConfig(
        from_email=env_value(env, "GENAI_REPORT_FROM"),
        to_email=env_value(env, "GENAI_REPORT_TO"),
        pdf_only_email=env_value(env, "GENAI_REPORT_PDF_ONLY_TO"),
        smtp_host=env_value(env, "SMTP_HOST"),
        smtp_port=env_int(env, "SMTP_PORT", 587),
        smtp_username=env_value(env, "SMTP_USERNAME"),
        smtp_password=env_value(env, "SMTP_PASSWORD"),
        smtp_use_tls=(env_value(env, "SMTP_USE_TLS", "true") or "true").lower() not in {"0", "false", "no"},
    )
    raw_social = raw.get("social", {})
    social_platforms = {
        item.lower()
        for item in env_csv(
            env,
            "SOCIAL_PLATFORMS",
            raw_social.get("platforms", ["x"]),
        )
    }
    social = SocialConfig(
        platforms=social_platforms,
        max_items_per_category=env_int(
            env,
            "SOCIAL_MAX_ITEMS_PER_CATEGORY",
            int(raw_social.get("max_items_per_category", 3)),
        ),
    )

    reports_dir = project_root / raw.get("reports_dir", "reports")
    state_path = project_root / raw.get("state_path", "state/sent_items.json")
    reports_dir.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        timezone=env_value(env, "DIGEST_TIMEZONE", raw.get("timezone", "Asia/Kolkata")) or "Asia/Kolkata",
        lookback_hours=env_int(env, "LOOKBACK_HOURS", int(raw.get("lookback_hours", 30))),
        max_items_per_category=env_int(env, "MAX_ITEMS_PER_CATEGORY", int(raw.get("max_items_per_category", 8))),
        categories=categories,
        rss_feeds=rss_feeds,
        arxiv=arxiv,
        email=email,
        reports_dir=reports_dir,
        state_path=state_path,
        request_timeout_seconds=env_int(
            env,
            "REQUEST_TIMEOUT_SECONDS",
            int(raw.get("request_timeout_seconds", 20)),
        ),
        social=social,
    )
