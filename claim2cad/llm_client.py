"""Thin OpenRouter chat-completions wrapper.

Phase 3 keeps this minimal: a single ``json_completion`` helper that posts to
``/chat/completions`` with response-format JSON, parses the result, and
retries on JSON-decode failure with exponential backoff. The parser uses it
only for non-golden claims; Phase 3's tests do not exercise this path.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from claim2cad.cost_tracker import record_call, should_downgrade

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"
DEFAULT_OPUS_MODEL = "anthropic/claude-opus-4.7"

# Some providers ignore response_format and wrap JSON in markdown fences.
# These regexes strip the wrapper so we can json.loads the inside.
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", re.DOTALL)
_BRACES_RE = re.compile(r"\{.*\}", re.DOTALL)

# Soft cap that triggers an Opus → Sonnet downgrade for the rest of the
# session. Override with ``CLAIM2CAD_COST_SOFT_CAP``.
DEFAULT_SOFT_CAP_USD = 60.0

# Task-type → tier. "heavy" = Opus, "routine" = Sonnet. Vision uses Opus.
HEAVY_TASKS = {
    "schema_design",
    "parser_improvement_reasoning",
    "debug_hard_failure",
    "vision_figure_parse",
    "prior_art_diff",
}
ROUTINE_TASKS = {
    "claim_parse",
    "claim_parse_korean",
    "batch_eval",
    "stub_classify",
    "small_extraction",
}


def _extract_json(content: str) -> Any:
    """Parse a JSON object from a model response that may be wrapped in
    markdown fences or surrounded by prose. Raises json.JSONDecodeError
    if no parseable object can be found."""
    if content is None:
        raise json.JSONDecodeError("response content was None", "", 0)
    s = content.strip()
    # Try direct parse first — when the model honors response_format properly.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Strip a markdown code fence (```json ... ``` or ``` ... ```).
    fence_match = _FENCE_RE.search(s)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    # Last resort: take the substring from the first '{' to the last '}'.
    braces_match = _BRACES_RE.search(s)
    if braces_match:
        return json.loads(braces_match.group(0))
    raise json.JSONDecodeError("no JSON object found in content", s[:200], 0)


def route(task_type: str) -> str:
    """Return the model name for a given task type, honouring downgrade flag."""
    soft_cap = float(os.environ.get("CLAIM2CAD_COST_SOFT_CAP", DEFAULT_SOFT_CAP_USD))
    downgraded = should_downgrade(soft_cap)
    opus_model = os.environ.get("OPENROUTER_OPUS_MODEL", DEFAULT_OPUS_MODEL)
    sonnet_model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    if task_type in HEAVY_TASKS and not downgraded:
        return opus_model
    if downgraded and task_type in HEAVY_TASKS:
        logger.info("Downgrade active: %s → %s for %s", opus_model, sonnet_model, task_type)
    return sonnet_model


class LLMConfigError(RuntimeError):
    """Raised when required env vars are missing."""


class LLMResponseError(RuntimeError):
    """Raised when the model never produces valid JSON."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "OPENROUTER_API_KEY is not set; copy .env.example to .env "
                "or use --dry-run."
            )
        return cls(
            api_key=api_key,
            model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
        )


def json_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    config: LLMConfig | None = None,
    max_retries: int = 2,
    timeout_s: float = 60.0,
    task_type: str = "claim_parse",
    model_override: str | None = None,
) -> dict[str, Any]:
    """Call OpenRouter and return the model's response parsed as JSON.

    Retries up to ``max_retries`` times with exponential backoff if the
    response body is not valid JSON. Network errors are *not* retried;
    they propagate so the caller sees them immediately.

    ``task_type`` selects the model via :func:`route` unless
    ``model_override`` is set. Every successful call is recorded in the
    cost tracker.
    """
    if config is None:
        config = LLMConfig.from_env()
    chosen_model = model_override or route(task_type)

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sungwon-chae/claim2cad",
        "X-Title": "Claim2CAD",
        "User-Agent": "Claim2CAD-research/1.0 (https://github.com/sungwon-chae/claim2cad)",
    }
    payload = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        logger.info(
            "LLM request attempt %d/%d (task=%s model=%s)",
            attempt,
            max_retries,
            task_type,
            chosen_model,
        )
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        record_call(task_type=task_type, model=chosen_model, response_body=body)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMResponseError(f"Unexpected OpenRouter response shape: {body!r}") from exc

        try:
            return _extract_json(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "LLM response was not parseable JSON on attempt %d (%s); "
                "head=%r; sleeping %ds before retry",
                attempt,
                exc,
                (content or "")[:80],
                backoff,
            )
            time.sleep(backoff)

    raise LLMResponseError(
        f"OpenRouter never produced valid JSON after {max_retries} attempts; "
        f"last error: {last_error}"
    )


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_OPUS_MODEL",
    "HEAVY_TASKS",
    "LLMConfig",
    "LLMConfigError",
    "LLMResponseError",
    "extract_json",
    "json_completion",
    "route",
]


# Public alias so other modules (e.g. llm_vision) don't have to import
# the underscore-prefixed name.
extract_json = _extract_json
