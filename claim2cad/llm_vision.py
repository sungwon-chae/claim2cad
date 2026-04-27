"""OpenRouter vision wrapper.

V1-3 uses this to send patent figure images to a vision-capable model
(default: claude-opus-4.7) and recover a structured JSON list of the
numbered component labels visible on the drawing.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from claim2cad.cost_tracker import record_call
from claim2cad.llm_client import (
    DEFAULT_BASE_URL,
    LLMConfig,
    LLMConfigError,  # noqa: F401  — re-export for callers
    LLMResponseError,
    extract_json,
)

logger = logging.getLogger(__name__)

DEFAULT_VISION_MODEL = "anthropic/claude-opus-4.7"


def _image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "image/png" if suffix == "png" else f"image/{suffix.replace('jpg', 'jpeg')}"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def vision_completion(
    *,
    image_path: Path,
    system_prompt: str,
    user_prompt: str,
    config: LLMConfig | None = None,
    max_retries: int = 2,
    timeout_s: float = 90.0,
    task_type: str = "vision_figure_parse",
    model_override: str | None = None,
) -> dict[str, Any]:
    """Send one image + text prompt to a vision-capable OpenRouter model
    and return the parsed JSON response. Records cost via
    :mod:`claim2cad.cost_tracker`.
    """
    if config is None:
        config = LLMConfig.from_env()

    chosen_model = (
        model_override
        or os.environ.get("OPENROUTER_VISION_MODEL")
        or DEFAULT_VISION_MODEL
    )

    if not image_path.exists() or image_path.stat().st_size < 1024:
        raise FileNotFoundError(f"Image missing or too small: {image_path}")

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sungwon-chae/claim2cad",
        "X-Title": "Claim2CAD",
        "User-Agent": "Claim2CAD-research/1.0 (https://github.com/sungwon-chae/claim2cad)",
    }
    data_url = _image_to_data_url(image_path)
    payload = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        logger.info(
            "Vision request attempt %d/%d (task=%s model=%s img=%s)",
            attempt,
            max_retries,
            task_type,
            chosen_model,
            image_path.name,
        )
        try:
            with httpx.Client(timeout=timeout_s) as client:
                response = client.post(
                    f"{(config.base_url or DEFAULT_BASE_URL)}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("Vision HTTP error on attempt %d: %s", attempt, exc)
            time.sleep(2 ** (attempt - 1))
            continue
        body = response.json()
        record_call(
            task_type=task_type,
            model=chosen_model,
            response_body=body,
            note=f"img={image_path.name}",
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMResponseError(f"Unexpected vision response shape: {body!r}") from exc
        try:
            return extract_json(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "Vision response was not JSON on attempt %d (head=%r); "
                "sleeping %ds before retry",
                attempt,
                (content or "")[:80],
                backoff,
            )
            time.sleep(backoff)

    raise LLMResponseError(
        f"Vision call never produced parseable JSON after {max_retries} "
        f"attempts; last_error={last_error}"
    )


__all__ = ["DEFAULT_VISION_MODEL", "vision_completion"]
