"""Rule-based pre-processing of a patent claim into structured segments.

Patent claims have a regular surface form: ``"<n>. <preamble>, comprising:
<element>; <element>; … wherein <clause>; and wherein <clause>."``. Splitting
on this skeleton before the LLM sees the text:

1. Disambiguates dependent vs. independent claims (look for
   ``"<n>. The X of claim N"``).
2. Lets the prompt cite element offsets that the LLM's character-counting
   isn't reliably good at.
3. Gives the validation-retry loop a structured fallback when the LLM emits
   something nonsensical.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_CLAIM_SPLIT_RE = re.compile(r"(?m)^(\d+)\.\s+")
_DEPENDENT_RE = re.compile(
    r"^The\s+.+?\s+of\s+claim\s+(\d+)\b",
    re.IGNORECASE,
)
_PREAMBLE_END_RE = re.compile(r",\s*comprising:\s*", re.IGNORECASE)
_WHEREIN_SPLIT_RE = re.compile(r"(?:^|\s+|;\s*)(?:and\s+)?wherein\b", re.IGNORECASE)


@dataclass
class ClaimSegments:
    """Structured breakdown of one claim's text."""

    claim_id: str
    text: str
    is_independent: bool = True
    depends_on: Optional[str] = None
    preamble: str = ""
    elements: list[str] = field(default_factory=list)
    wherein_clauses: list[str] = field(default_factory=list)


def _split_into_claims(full_text: str) -> list[tuple[str, str]]:
    """Return [(claim_id, claim_text), ...] for each numbered claim found."""
    parts = _CLAIM_SPLIT_RE.split(full_text)
    # parts looks like ['', '1', 'claim 1 body', '2', 'claim 2 body', ...]
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        number = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        body = body.rstrip()
        if not body:
            continue
        out.append((f"claim_{number}", body))
    return out


def _segment_one(claim_id: str, text: str) -> ClaimSegments:
    seg = ClaimSegments(claim_id=claim_id, text=text)

    dep_match = _DEPENDENT_RE.match(text)
    if dep_match:
        seg.is_independent = False
        seg.depends_on = f"claim_{dep_match.group(1)}"

    # Split off wherein clauses first — they often contain commas/semicolons
    # that would confuse the element split.
    wherein_split = _WHEREIN_SPLIT_RE.split(text)
    body = wherein_split[0].rstrip(" .;")
    for tail in wherein_split[1:]:
        cleaned = tail.strip(" .;")
        if cleaned:
            seg.wherein_clauses.append(f"wherein {cleaned}")

    # Preamble is the prefix up through "comprising:" (when present).
    pre_match = _PREAMBLE_END_RE.search(body)
    if pre_match:
        seg.preamble = body[: pre_match.start()].strip()
        elements_blob = body[pre_match.end() :]
    else:
        seg.preamble = body.strip()
        elements_blob = ""

    if elements_blob:
        # Elements are separated by ";"; the "and" before the last is
        # cosmetic.
        for raw in elements_blob.split(";"):
            element = raw.strip().strip(",").strip()
            if element.lower().startswith("and "):
                element = element[4:].strip()
            element = element.rstrip(" .")
            if element:
                seg.elements.append(element)

    return seg


def segment_claim(full_text: str) -> list[ClaimSegments]:
    """Return one :class:`ClaimSegments` per numbered claim in the text."""
    parts = _split_into_claims(full_text.strip())
    if not parts:
        # No "1." numbering — treat the whole input as a single claim.
        return [_segment_one("claim_1", full_text.strip())]

    segs = [_segment_one(cid, body) for cid, body in parts]
    logger.debug(
        "Segmented %d claim(s); first has %d elements, %d wherein clauses",
        len(segs),
        len(segs[0].elements),
        len(segs[0].wherein_clauses),
    )
    return segs


__all__ = ["ClaimSegments", "segment_claim"]
