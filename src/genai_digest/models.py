from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256


@dataclass(slots=True)
class Article:
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str
    categories: set[str] = field(default_factory=set)
    source_type: str = "news"
    score: float = 0.0

    @property
    def id(self) -> str:
        payload = f"{self.url.strip()}|{self.title.strip().lower()}"
        return sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class DigestResult:
    generated_at: datetime
    grouped_articles: dict[str, list[Article]]
    top_articles: list[Article]
    total_articles: int
    warnings: list[str]

