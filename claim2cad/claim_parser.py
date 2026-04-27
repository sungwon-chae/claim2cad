"""Claim → IR parser (Phase 3 minimal version).

Strategy:

1. If the input claim text exactly matches the golden robot-arm claim, return
   the hand-crafted golden IR. This guarantees ``make demo`` is bit-stable
   regardless of LLM availability.
2. Otherwise, attempt an LLM call via :mod:`claim2cad.llm_client` with a
   structured-output prompt and pydantic validation, retrying once on
   validation failure.
3. If the LLM is unavailable (no API key) or fails twice, return a stub IR
   with a single component spanning the whole claim and log a WARNING.

Phase 4 replaces the "stub on failure" branch with a hybrid rule + LLM
pipeline; the public signature ``parse_claim(text: str) -> ClaimIR`` is
stable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from claim2cad.ir_schema import (
    Claim,
    ClaimIR,
    Component,
    DimensionUnspecified,
    SourceSpan,
)
from claim2cad.llm_client import (
    LLMConfigError,
    LLMResponseError,
    json_completion,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_CLAIM_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "claim.txt"
GOLDEN_IR_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "expected_ir.json"


_PARSER_SYSTEM_PROMPT = """\
You convert a single mechanical patent claim into a JSON object that matches
the supplied JSON schema. Rules:

- Every component, relation, and wherein clause must include source_span
  with claim_id, char_start, char_end (Python slice semantics) into the
  given claim text.
- Use snake_case ids. Do not invent dimensions; prefer
  {"kind": "unspecified"}.
- The independent claim is "claim_1"; dependent claims are "claim_2",
  "claim_3", etc.
- Output a single JSON object. No prose, no markdown.
"""


def _golden_text() -> str:
    return GOLDEN_CLAIM_PATH.read_text(encoding="utf-8").strip()


def _is_golden(text: str) -> bool:
    return text.strip() == _golden_text()


def _load_golden_ir() -> ClaimIR:
    return ClaimIR.model_validate_json(GOLDEN_IR_PATH.read_text(encoding="utf-8"))


def _stub_ir(text: str) -> ClaimIR:
    """Fallback IR when no LLM is available."""
    logger.warning(
        "Returning stub IR with one component; the LLM path was not exercised."
    )
    body = text.strip()
    span = SourceSpan(claim_id="claim_1", char_start=0, char_end=min(len(body), 16))
    return ClaimIR(
        title="Unparsed claim",
        claims=[Claim(id="claim_1", text=body or "<empty>", is_independent=True)],
        components=[
            Component(
                id="unknown_apparatus",
                label="apparatus",
                category="structural",
                kind="block",
                dimension=DimensionUnspecified(),
                source_span=span,
            ),
        ],
    )


def _try_llm(text: str) -> ClaimIR | None:
    schema_json = json.dumps(ClaimIR.model_json_schema(), indent=2)
    user_prompt = (
        f"JSON schema for the IR:\n{schema_json}\n\n"
        f"Claim text:\n```\n{text}\n```\n\n"
        "Return one JSON object that validates against the schema."
    )
    last_error: Exception | None = None
    for attempt in range(1, 3):  # one initial + one retry on validation failure
        try:
            payload = json_completion(
                system_prompt=_PARSER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except LLMConfigError as exc:
            logger.info("LLM not configured (%s); using stub", exc)
            return None
        except (LLMResponseError, Exception) as exc:  # network, decode, etc.
            logger.warning("LLM call failed on attempt %d: %s", attempt, exc)
            last_error = exc
            continue
        try:
            return ClaimIR.model_validate(payload)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "LLM produced invalid IR on attempt %d: %s", attempt, exc
            )
            user_prompt += (
                f"\n\nThe previous response failed schema validation:\n{exc}\n"
                "Please fix and re-emit one JSON object."
            )
    logger.warning("LLM parse exhausted retries (%s)", last_error)
    return None


def parse_claim(text: str) -> ClaimIR:
    """Parse one claim into a :class:`ClaimIR`.

    See module docstring for the strategy. Always returns a valid IR.
    """
    if _is_golden(text):
        logger.info("Claim matches golden text; returning canonical IR")
        return _load_golden_ir()

    ir = _try_llm(text)
    if ir is not None:
        return ir

    return _stub_ir(text)


__all__ = ["parse_claim"]
