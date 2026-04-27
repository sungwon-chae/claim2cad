"""Per-call cost tracking for OpenRouter LLM calls.

Logs every call to ``logs/cost_tracker.json`` as a JSON-lines stream and
maintains a rolling cumulative total. Pricing is approximate; OpenRouter
returns its own usage in the response and we use that when available.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "logs" / "cost_tracker.json"

# Approximate USD per million tokens (input, output). Falls back to these
# when OpenRouter doesn't return upstream cost in the body.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "anthropic/claude-opus-4.7": (15.0, 75.0),
    "anthropic/claude-opus-4-7": (15.0, 75.0),
    "anthropic/claude-sonnet-4.6": (3.0, 15.0),
    "anthropic/claude-sonnet-4-6": (3.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "anthropic/claude-haiku-4.5": (0.80, 4.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.0),
}

_LOCK = threading.Lock()


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_per_m, out_per_m = PRICE_TABLE.get(model, (5.0, 15.0))
    return (prompt_tokens * in_per_m + completion_tokens * out_per_m) / 1_000_000.0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def record_call(
    *,
    task_type: str,
    model: str,
    response_body: dict[str, Any] | None,
    note: str = "",
) -> dict[str, Any]:
    """Record a completed OpenRouter call. ``response_body`` may be None
    (e.g. when the call errored before returning usage)."""
    usage = (response_body or {}).get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    # OpenRouter reports cost as either ``response.cost`` (older) or
    # ``response.usage.cost`` (current). Prefer the latter.
    upstream_cost = usage.get("cost")
    if upstream_cost is None:
        upstream_cost = (response_body or {}).get("cost")
    if upstream_cost is not None:
        cost_usd = float(upstream_cost)
    else:
        cost_usd = _estimate_cost(model, prompt_tokens, completion_tokens)

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task_type": task_type,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost_usd, 6),
        "note": note,
    }

    with _LOCK:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    return entry


def cumulative_cost() -> float:
    return sum(float(r.get("cost_usd", 0.0)) for r in _read_jsonl(LOG_PATH))


def cost_summary() -> dict[str, Any]:
    rows = _read_jsonl(LOG_PATH)
    by_task: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for r in rows:
        c = float(r.get("cost_usd", 0.0))
        by_task[r.get("task_type", "?")] = by_task.get(r.get("task_type", "?"), 0.0) + c
        by_model[r.get("model", "?")] = by_model.get(r.get("model", "?"), 0.0) + c
    return {
        "total_calls": len(rows),
        "total_cost_usd": round(sum(by_task.values()), 4),
        "by_task": {k: round(v, 4) for k, v in sorted(by_task.items(), key=lambda kv: -kv[1])},
        "by_model": {k: round(v, 4) for k, v in sorted(by_model.items(), key=lambda kv: -kv[1])},
    }


# Cap-and-downgrade -----------------------------------------------------------
# When cumulative cost crosses the soft cap, route opus calls to sonnet for
# the remainder of the session.

DOWNGRADE_FILE = REPO_ROOT / "logs" / "downgrade_active.flag"


def should_downgrade(soft_cap_usd: float) -> bool:
    if DOWNGRADE_FILE.exists():
        return True
    if cumulative_cost() >= soft_cap_usd:
        DOWNGRADE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DOWNGRADE_FILE.write_text(
            f"Triggered at {time.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"(cumulative=${cumulative_cost():.2f}, cap=${soft_cap_usd:.2f})\n",
            encoding="utf-8",
        )
        logger.warning(
            "Cost soft-cap $%.2f exceeded (cumulative=$%.2f); downgrading Opus → Sonnet",
            soft_cap_usd,
            cumulative_cost(),
        )
        return True
    return False


__all__ = [
    "record_call",
    "cumulative_cost",
    "cost_summary",
    "should_downgrade",
    "DOWNGRADE_FILE",
    "LOG_PATH",
]
