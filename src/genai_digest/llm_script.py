from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig
from .models import DigestResult

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """You are a podcast script writer. Rewrite the provided outline into a natural,
engaging two-host conversation in the style of an AI-generated audio overview.

Rules:
- Exactly two speakers, labelled `HOST A:` and `HOST B:` at the start of every line.
- Keep every story from the outline; do not invent facts, numbers, or stories.
- Conversational tone: contractions, brief reactions, smooth handoffs, varied
  sentence length. Hosts can briefly build on each other, but stay factual.
- Attribute stories to their sources when the outline names them.
- Target 700-950 words total. Plain text only, no markdown, no stage directions.
- Start with a short welcome and end with a short sign-off."""


def polish_dialogue(template_script: str, digest: DigestResult, config: AppConfig) -> str | None:
    """Rewrite the template dialogue with a free LLM if configured.

    Uses GitHub Models (free tier, authenticated with GITHUB_TOKEN which is
    available in every GitHub Actions run when the workflow requests
    `models: read` permission). Returns None when disabled or on any failure,
    so callers fall back to the deterministic template script.
    """
    if os.environ.get("LLM_SCRIPT_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    token = os.environ.get("LLM_API_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return None

    endpoint = os.environ.get("LLM_API_ENDPOINT", GITHUB_MODELS_ENDPOINT)
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Rewrite this outline into the two-host script:\n\n" + template_script,
            },
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str) or "HOST A:" not in content.upper():
        return None
    return content.strip() + "\n"
