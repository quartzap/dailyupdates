from __future__ import annotations

from datetime import datetime, timedelta

from .models import Article


def build_sample_articles(now: datetime) -> list[Article]:
    return [
        Article(
            title="Model vendor launches enterprise multimodal assistant for finance teams",
            url="https://example.com/product-launch",
            source="Example News",
            published_at=now - timedelta(hours=2),
            summary="The release focuses on document reasoning, spreadsheet copilots, and secure deployment.",
            categories={"product_announcements"},
            source_type="news",
        ),
        Article(
            title="Chipmaker announces new AI accelerator optimized for inference at scale",
            url="https://example.com/hardware",
            source="Example Hardware",
            published_at=now - timedelta(hours=3),
            summary="The hardware update promises better performance-per-watt for large language model serving.",
            categories={"hardware"},
            source_type="news",
        ),
        Article(
            title="Major bank signs GenAI platform deal to automate compliance workflows",
            url="https://example.com/trade-deal",
            source="Example Markets",
            published_at=now - timedelta(hours=4),
            summary="The agreement covers document review, risk classification, and employee copilots.",
            categories={"trade_deals", "industry_use_cases"},
            source_type="news",
        ),
        Article(
            title="Hospital network deploys generative AI assistant for discharge summaries",
            url="https://example.com/use-case",
            source="Example Health",
            published_at=now - timedelta(hours=5),
            summary="The use case highlights clinician note drafting and patient communication workflows.",
            categories={"industry_use_cases"},
            source_type="news",
        ),
        Article(
            title="New paper improves retrieval grounding for long-context language models",
            url="https://arxiv.org/abs/2607.00001",
            source="arXiv",
            published_at=now - timedelta(hours=6),
            summary="Researchers propose a lightweight retrieval strategy that improves faithfulness on long documents.",
            categories={"research_papers"},
            source_type="paper",
        ),
    ]

