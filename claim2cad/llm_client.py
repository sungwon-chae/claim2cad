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
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"


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
    max_retries: int = 3,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Call OpenRouter and return the model's response parsed as JSON.

    Retries up to ``max_retries`` times with exponential backoff if the
    response body is not valid JSON. Network errors are *not* retried; they
    propagate so the caller sees them immediately.
    """
    if config is None:
        config = LLMConfig.from_env()

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo/claim2cad",
        "X-Title": "Claim2CAD",
    }
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        logger.info("LLM request attempt %d/%d (model=%s)", attempt, max_retries, config.model)
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMResponseError(f"Unexpected OpenRouter response shape: {body!r}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "LLM response was not valid JSON on attempt %d (%s); "
                "sleeping %ds before retry",
                attempt,
                exc,
                backoff,
            )
            time.sleep(backoff)

    raise LLMResponseError(
        f"OpenRouter never produced valid JSON after {max_retries} attempts; "
        f"last error: {last_error}"
    )


__all__ = [
    "LLMConfig",
    "LLMConfigError",
    "LLMResponseError",
    "json_completion",
]
