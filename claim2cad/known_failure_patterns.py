"""Curated catalogue of failure patterns observed when running the v0.1.0
pipeline on real patents.

Populated incrementally from V1-2 iteration runs. Each entry has:

- ``id``: stable identifier
- ``description``: one-line failure shape
- ``detect``: regex (matched against ``error`` or ``warning`` strings) or
  predicate name
- ``mitigation``: what V1-2 changed (or noted as future work)
- ``status``: ``"observed" | "mitigated" | "deferred"``

The validator tags each result's ``failure_signatures`` with the matching
IDs so downstream reports can filter / aggregate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Pattern


@dataclass(frozen=True)
class FailurePattern:
    id: str
    description: str
    detect: Pattern[str]
    mitigation: str
    status: str = "observed"


PATTERNS: list[FailurePattern] = [
    FailurePattern(
        id="P001-markdown-fenced-json",
        description="Model wraps JSON in a ```json fence despite response_format.",
        detect=re.compile(r"Expecting value: line 1 column 1 \(char 0\)"),
        mitigation="llm_client._extract_json strips fences before json.loads.",
        status="mitigated",
    ),
    FailurePattern(
        id="P002-glb-empty-when-zero-components",
        description="GLB file has glTF magic but no scene nodes when IR is empty.",
        detect=re.compile(r"glb_missing_or_tiny|GLB.*0 root children"),
        mitigation="Stub IR ensures ≥1 component; pipeline rejects 0-component IRs.",
        status="observed",
    ),
    FailurePattern(
        id="P003-cmap-count-mismatch",
        description="claim_map count diverges from IR component count.",
        detect=re.compile(r"cmap_count_mismatch"),
        mitigation="mapping.build_claim_map iterates ir.components verbatim.",
        status="observed",
    ),
    FailurePattern(
        id="P004-llm-validation-error",
        description="LLM emits valid JSON but fails pydantic schema validation.",
        detect=re.compile(r"ir_validation|ValidationError"),
        mitigation="Parser retries once with the validation error fed back.",
        status="observed",
    ),
    FailurePattern(
        id="P005-empty-claim-section",
        description="Patent HTML has no claim 1 (e.g. design patent).",
        detect=re.compile(r"empty_claim|missing_claim_txt"),
        mitigation="Patent collector rejects at fetch time.",
        status="mitigated",
    ),
]


def signatures_for(messages: list[str]) -> list[str]:
    found: list[str] = []
    text = "\n".join(messages)
    for p in PATTERNS:
        if p.detect.search(text):
            found.append(p.id)
    return found


__all__ = ["FailurePattern", "PATTERNS", "signatures_for"]
