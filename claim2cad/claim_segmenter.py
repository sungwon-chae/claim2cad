"""Rule-based pre-processing of a patent claim into structured segments.

Patent claims have a regular surface form. For US claims:

    "<n>. <preamble>, comprising: <element>; <element>; … wherein <clause>; and wherein <clause>."

For Korean (KIPO/KIPRIS) claims:

    "【청구항 N】 <element>; <element>; … 를 포함하는 <preamble>."

Splitting on this skeleton before the LLM sees the text:

1. Disambiguates dependent vs. independent claims (look for
   ``"<n>. The X of claim N"`` / ``"제N항에 따른"``).
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

from claim2cad.lang import Language, detect_language
from claim2cad.lang_ko import (
    CLAIM_SPLIT_RE as KO_CLAIM_SPLIT_RE,
    DEPENDENT_RE as KO_DEPENDENT_RE,
    ELEMENT_SPLIT_RE as KO_ELEMENT_SPLIT_RE,
    PREAMBLE_TAIL_RE as KO_PREAMBLE_TAIL_RE,
)

logger = logging.getLogger(__name__)

# English (default) regexes.
_CLAIM_SPLIT_RE = re.compile(r"(?m)^(\d+)\.\s+")
_DEPENDENT_RE = re.compile(
    r"^The\s+.+?\s+of\s+claim\s+(\d+)\b",
    re.IGNORECASE,
)
_PREAMBLE_END_RE = re.compile(r",\s*comprising:\s*", re.IGNORECASE)
_WHEREIN_SPLIT_RE = re.compile(r"(?:^|\s+|;\s*)(?:and\s+)?wherein\b", re.IGNORECASE)

# Korean wherein-equivalents. ``여기서`` (here) and ``이때`` (at this time)
# introduce explanatory clauses; we treat them like wherein for symmetry.
_KO_WHEREIN_SPLIT_RE = re.compile(
    r"(?:^|;\s*|\s+)(여기서|이때|상기에\s*있어서)\s*",
)


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
    language: Language = "en"


# ---------------------------------------------------------------------------
# English
# ---------------------------------------------------------------------------


def _split_into_claims_en(full_text: str) -> list[tuple[str, str]]:
    """Return [(claim_id, claim_text), ...] for each numbered claim found."""
    parts = _CLAIM_SPLIT_RE.split(full_text)
    out: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        number = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        body = body.rstrip()
        if not body:
            continue
        out.append((f"claim_{number}", body))
    return out


def _segment_one_en(claim_id: str, text: str) -> ClaimSegments:
    seg = ClaimSegments(claim_id=claim_id, text=text, language="en")

    dep_match = _DEPENDENT_RE.match(text)
    if dep_match:
        seg.is_independent = False
        seg.depends_on = f"claim_{dep_match.group(1)}"

    wherein_split = _WHEREIN_SPLIT_RE.split(text)
    body = wherein_split[0].rstrip(" .;")
    for tail in wherein_split[1:]:
        cleaned = tail.strip(" .;")
        if cleaned:
            seg.wherein_clauses.append(f"wherein {cleaned}")

    pre_match = _PREAMBLE_END_RE.search(body)
    if pre_match:
        seg.preamble = body[: pre_match.start()].strip()
        elements_blob = body[pre_match.end() :]
    else:
        seg.preamble = body.strip()
        elements_blob = ""

    if elements_blob:
        for raw in elements_blob.split(";"):
            element = raw.strip().strip(",").strip()
            if element.lower().startswith("and "):
                element = element[4:].strip()
            element = element.rstrip(" .")
            if element:
                seg.elements.append(element)

    return seg


# ---------------------------------------------------------------------------
# Korean
# ---------------------------------------------------------------------------


def _split_into_claims_ko(full_text: str) -> list[tuple[str, str]]:
    """Return [(claim_id, claim_text), ...] for Korean claim numbering.

    Accepts ``【청구항 N】`` headers and ``N.`` numbering.
    """
    parts = KO_CLAIM_SPLIT_RE.split(full_text)
    # KO regex has two capturing groups; only one is non-None per match.
    out: list[tuple[str, str]] = []
    # parts: ['<prefix>', g1, g2, body, g1, g2, body, ...]
    i = 1
    while i + 2 < len(parts) + 1:
        if i + 1 >= len(parts):
            break
        number = parts[i] or parts[i + 1]
        body_idx = i + 2
        if body_idx >= len(parts):
            break
        body = parts[body_idx].rstrip()
        if number and body:
            out.append((f"claim_{number}", body))
        i += 3
    return out


def _segment_one_ko(claim_id: str, text: str) -> ClaimSegments:
    seg = ClaimSegments(claim_id=claim_id, text=text, language="ko")

    dep_match = KO_DEPENDENT_RE.search(text[:80])
    if dep_match:
        seg.is_independent = False
        seg.depends_on = f"claim_{dep_match.group(1)}"

    # Pull off "wherein"-equivalents (여기서/이때). Korean writers mostly put
    # them at the end, but this is permissive.
    wherein_split = _KO_WHEREIN_SPLIT_RE.split(text)
    if len(wherein_split) > 1:
        body = wherein_split[0].rstrip(" .;。")
        # Pairs of (marker, clause_text).
        i = 1
        while i + 1 < len(wherein_split):
            marker = wherein_split[i]
            clause = wherein_split[i + 1].strip(" .;。")
            if clause:
                seg.wherein_clauses.append(f"{marker} {clause}".strip())
            i += 2
    else:
        body = text.rstrip(" .;。")

    # The trailing preamble: ``...를 포함하는 <noun>``. We pull it off so
    # what's left are the element list.
    pre_match = KO_PREAMBLE_TAIL_RE.search(body)
    if pre_match:
        # Preamble is "verb + noun-phrase"; for IR title we just want the
        # noun phrase.
        seg.preamble = pre_match.group(2).strip()
        body = body[: pre_match.start()].rstrip(" ;,。.")
    else:
        seg.preamble = ""

    # Drop a leading dependent-claim header (e.g. "제1항에 따른 매니퓰레이터에
    # 있어서,"). Keep what follows for element splitting.
    if seg.depends_on:
        comma = body.find(",")
        if 0 < comma < 80:
            body = body[comma + 1 :].strip()

    for raw in KO_ELEMENT_SPLIT_RE.split(body):
        element = raw.strip().strip(",").rstrip(" .;。")
        if element:
            seg.elements.append(element)

    # If the preamble produced no body elements (e.g. a dependent claim that
    # has only a single element), keep what we have — the parser handles
    # zero-element segments.
    return seg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def segment_claim(full_text: str) -> list[ClaimSegments]:
    """Return one :class:`ClaimSegments` per numbered claim in the text."""
    text = full_text.strip()
    language: Language = detect_language(text)

    if language == "ko":
        parts = _split_into_claims_ko(text)
        if not parts:
            return [_segment_one_ko("claim_1", text)]
        segs = [_segment_one_ko(cid, body) for cid, body in parts]
    else:
        parts = _split_into_claims_en(text)
        if not parts:
            return [_segment_one_en("claim_1", text)]
        segs = [_segment_one_en(cid, body) for cid, body in parts]

    logger.debug(
        "Segmented %d claim(s) [lang=%s]; first has %d elements, %d wherein clauses",
        len(segs),
        language,
        len(segs[0].elements),
        len(segs[0].wherein_clauses),
    )
    return segs


__all__ = ["ClaimSegments", "segment_claim"]
