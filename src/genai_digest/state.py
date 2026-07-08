from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


def load_seen_items(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("sent", {})


def save_seen_items(path: Path, existing: dict[str, str], item_ids: list[str], now: datetime) -> None:
    pruned = prune_seen_items(existing, now, retention_days=21)
    for item_id in item_ids:
        pruned[item_id] = now.isoformat()
    payload = {
        "last_updated": now.isoformat(),
        "sent": pruned,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def prune_seen_items(seen: dict[str, str], now: datetime, retention_days: int) -> dict[str, str]:
    cutoff = now - timedelta(days=retention_days)
    kept: dict[str, str] = {}
    for key, raw_timestamp in seen.items():
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            continue
        if timestamp >= cutoff:
            kept[key] = raw_timestamp
    return kept

