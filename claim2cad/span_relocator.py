"""Re-locate ``source_span`` offsets to actual substrings of the claim text.

The LLM-emitted ``source_span.char_start`` / ``char_end`` offsets are
notoriously unreliable: even when the schema asks for "Python string
character offsets", the model often counts tokens, words, or some
non-canonical normalised form. The drift is cumulative — the first
component is off by 1 char, the next by 2, and so on. The viewer's
underline ends up bracketing the wrong substring (e.g.
``"d. a p(ower~)"`` instead of ``"power"``).

This module fixes the offsets after the LLM step by **searching for
the component's ``label`` (or one of its aliases) in the claim text
directly**. The new offsets are guaranteed to either point at a real
substring or be flagged ``unverified=True`` so the viewer can hide the
underline.

Algorithm:

1. Build a list of search keys per component:
    a. exact ``label``
    b. lowercase
    c. label with " - " ↔ "-" normalised both ways
    d. label without parenthesised disambiguators (e.g.
       ``"pintle pin hole (main member)" → "pintle pin hole"``)
    e. label with prepositional tail trimmed
       (``"stop means on pintle pin" → "stop means"``)
    f. claim-text aliases harvested from common patent-claim variants
       (case-insensitive plural, hyphenation variants).

2. For each key, find ALL non-overlapping occurrences in the claim
   text. Score occurrences by:
    a. proximity to the LLM's hinted ``char_start`` (less is better);
    b. word-boundary alignment;
    c. preference for the FIRST occurrence in the claim (because
       claim drafting introduces components left-to-right at first
       use). If two components contend for the same occurrence we
       prefer the one whose label is the longer match.

3. Run a global de-duplication pass: each character range can be the
   primary span for at most one component. Tie-breaking favours the
   component_id whose key matched longer; loser falls back to its
   second-best occurrence.

4. Emit a debug artefact at the caller's request listing every
   component's chosen span, the substring extracted, the expected
   substring, and pass/fail.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


_PAREN_DISAMBIG = re.compile(r"\s*\([^()]*\)\s*$")
_TAIL_PREP = re.compile(r"\s+(on|of|for|to|in|by|with|from|at)\s+.*$", re.IGNORECASE)
_HYPHENS = re.compile(r"[‐-―\-]")
_WHITESPACE = re.compile(r"\s+")


def _strip_parenthetical(s: str) -> str:
    """``"pintle pin hole (main member)" → "pintle pin hole"``."""
    return _PAREN_DISAMBIG.sub("", s).strip()


def _strip_prep_tail(s: str) -> str:
    """``"stop means on pintle pin" → "stop means"``. Heuristic: drops
    everything after a preposition in the middle/end."""
    return _TAIL_PREP.sub("", s).strip()


def _normalise_hyphens(s: str) -> str:
    """All Unicode hyphens → ``-``."""
    return _HYPHENS.sub("-", s)


def _hyphen_variants(s: str) -> list[str]:
    """Return ``[s, s_with_hyphens_to_spaces, s_with_spaces_to_hyphens]``,
    deduplicated."""
    out = [s]
    no_hyphen = s.replace("-", " ")
    no_hyphen = _WHITESPACE.sub(" ", no_hyphen).strip()
    if no_hyphen != s:
        out.append(no_hyphen)
    space_to_hyphen = re.sub(r"\b(\w+)\s+(\w+)\b", r"\1-\2", s)
    if space_to_hyphen != s and space_to_hyphen not in out:
        out.append(space_to_hyphen)
    return out


def _generate_keys(label: str) -> list[str]:
    """Return a list of ordered search keys (longest/most-specific first)."""
    if not label:
        return []
    keys: list[str] = []
    seen: set[str] = set()

    def _add(s: str) -> None:
        ss = _WHITESPACE.sub(" ", _normalise_hyphens(s)).strip()
        if not ss or ss.lower() in seen:
            return
        keys.append(ss)
        seen.add(ss.lower())

    _add(label)
    stripped_paren = _strip_parenthetical(label)
    if stripped_paren and stripped_paren != label:
        _add(stripped_paren)
    stripped_prep = _strip_prep_tail(stripped_paren)
    if stripped_prep and stripped_prep != stripped_paren:
        _add(stripped_prep)

    # Hyphenation variants for every key generated so far.
    for k in list(keys):
        for v in _hyphen_variants(k):
            _add(v)
    return keys


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass
class SpanCandidate:
    component_id: str
    key: str
    start: int
    end: int
    distance_from_hint: int
    word_boundary_score: float

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def composite_score(self) -> float:
        # Lower is better.
        return self.distance_from_hint - 100 * self.word_boundary_score


_WORD_BOUNDARY_BEFORE = re.compile(r"(^|[\s\(\[,;:])$")
_WORD_BOUNDARY_AFTER = re.compile(r"^([\s\)\]\.,;:]|$)")


def _word_boundary_score(text: str, start: int, end: int) -> float:
    before_ok = start == 0 or bool(_WORD_BOUNDARY_BEFORE.search(text[max(0, start - 1) : start + 1][:-1] or ""))
    # simplified: peek at characters
    bc = text[start - 1] if start > 0 else ""
    ac = text[end] if end < len(text) else ""
    score = 0.0
    if start == 0 or not bc.isalnum():
        score += 0.5
    if end == len(text) or not ac.isalnum():
        score += 0.5
    return score


_STOP_TOKENS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "said"}


def _label_content_tokens(label: str) -> list[str]:
    """Extract content tokens from a label, dropping stopwords + casing."""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", label.lower())
    return [t for t in raw if t and t not in _STOP_TOKENS]


def _token_set_occurrences(
    text: str,
    label: str,
    *,
    max_window: int = 60,
) -> list[tuple[int, int]]:
    """Find spans where every content token of ``label`` appears in
    order within a window of ``max_window`` characters.

    Designed for patent-claim coordination: the singular "upper parallel
    extension" appears in the claim as the plural "upper and lower
    parallel extensions". The token sequence ``["upper", "parallel",
    "extension"]`` still appears in order; we just need to capture the
    range from the first to the last token (which is what the user
    wants underlined)."""
    tokens = _label_content_tokens(label)
    if len(tokens) < 2:
        return []
    text_l = text.lower()
    # Find candidate positions for each token (allowing prefix match for
    # plurals: "extensions" matches "extension").
    token_positions: list[list[int]] = []
    for tok in tokens:
        positions: list[int] = []
        # word-boundary search; allow trailing 's' or 'es' for plural form
        pat = re.compile(rf"\b{re.escape(tok)}(?:s|es)?\b")
        for m in pat.finditer(text_l):
            positions.append(m.start())
        if not positions:
            return []  # token absent from text → bail
        token_positions.append(positions)

    out: list[tuple[int, int]] = []
    # Greedy: try every starting position for token 0; advance through
    # the others by finding their next position > previous + 1.
    for start_pos in token_positions[0]:
        cur = start_pos
        last_pos = start_pos
        ok = True
        for k in range(1, len(tokens)):
            next_candidates = [p for p in token_positions[k] if p > last_pos]
            if not next_candidates:
                ok = False
                break
            nxt = min(next_candidates)
            if nxt - start_pos > max_window:
                ok = False
                break
            last_pos = nxt
        if ok:
            # End is the last token's word-end. Find it via regex again.
            tail = tokens[-1]
            pat = re.compile(rf"\b{re.escape(tail)}(?:s|es)?\b")
            m = pat.search(text_l, last_pos)
            if m:
                out.append((start_pos, m.end()))
    return out


def _all_occurrences(text: str, key: str, *, case_insensitive: bool = True) -> list[tuple[int, int]]:
    """Find all non-overlapping, word-boundary-friendly occurrences."""
    out: list[tuple[int, int]] = []
    if not key:
        return out
    haystack = text.lower() if case_insensitive else text
    needle = key.lower() if case_insensitive else key
    pos = 0
    while True:
        idx = haystack.find(needle, pos)
        if idx < 0:
            break
        out.append((idx, idx + len(key)))
        pos = idx + max(1, len(key) // 2)  # allow overlapping but advance
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class RelocatedSpan:
    component_id: str
    claim_id: str
    char_start: int
    char_end: int
    extracted: str
    matched_key: str
    verified: bool
    notes: str = ""


def relocate_components(
    *,
    claims_text_by_id: dict[str, str],
    components: list[dict[str, Any]],
) -> list[RelocatedSpan]:
    """Re-locate one span per component.

    ``components`` is a list of dicts like::

        {
            "id": "pintle_pin",
            "label": "pintle pin",
            "source_span": {"claim_id": "claim_1", "char_start": 163, "char_end": 173},
        }

    Returns one ``RelocatedSpan`` per component (verified=True if a
    confident match was found, else verified=False with the original
    offsets clamped to the claim length).
    """
    # Collect all candidates across all components, then resolve
    # conflicts so each character range is owned by at most one
    # component.
    all_candidates: list[SpanCandidate] = []
    components_by_id: dict[str, dict[str, Any]] = {c["id"]: c for c in components}

    for comp in components:
        cid = comp["id"]
        claim_id = comp["source_span"]["claim_id"]
        hint_start = int(comp["source_span"]["char_start"])
        text = claims_text_by_id.get(claim_id, "")
        if not text:
            continue
        for key in _generate_keys(comp.get("label") or ""):
            for s, e in _all_occurrences(text, key):
                cand = SpanCandidate(
                    component_id=cid,
                    key=key,
                    start=s,
                    end=e,
                    distance_from_hint=abs(s - hint_start),
                    word_boundary_score=_word_boundary_score(text, s, e),
                )
                all_candidates.append(cand)
        # Token-set fallback: when the strict-label keys don't match,
        # patent text often coordinates singular forms ("upper parallel
        # extension") into a plural ("upper and lower parallel extensions").
        # We find a window containing every label token in order, capped
        # at a reasonable span length.
        label = comp.get("label") or ""
        existing_for_comp = [c for c in all_candidates if c.component_id == cid]
        if not existing_for_comp:
            for s, e in _token_set_occurrences(text, label):
                cand = SpanCandidate(
                    component_id=cid,
                    key=f"token-set:{label}",
                    start=s,
                    end=e,
                    distance_from_hint=abs(s - hint_start),
                    word_boundary_score=_word_boundary_score(text, s, e),
                )
                all_candidates.append(cand)

    # Greedy assignment: for each component, pick its best candidate
    # not yet taken by another component. Process components in order
    # of label length (longer first) so specific labels lock in their
    # positions before generic ones compete.
    components_sorted = sorted(
        components,
        key=lambda c: -len(c.get("label") or ""),
    )
    taken_ranges: list[tuple[int, int, str]] = []  # (start, end, owner_cid)
    chosen: dict[str, SpanCandidate] = {}

    cands_by_id: dict[str, list[SpanCandidate]] = {}
    for c in all_candidates:
        cands_by_id.setdefault(c.component_id, []).append(c)
    for v in cands_by_id.values():
        v.sort(key=lambda c: c.composite_score)

    def _conflicts(s: int, e: int) -> str | None:
        for ts, te, owner in taken_ranges:
            # Overlap test
            if s < te and e > ts:
                # If new range is strictly contained, allow only if the
                # new range is significantly shorter (sub-feature inside
                # a longer named element). Otherwise it's a conflict.
                if s >= ts and e <= te and (e - s) < (te - ts) * 0.6:
                    continue
                if ts >= s and te <= e and (te - ts) < (e - s) * 0.6:
                    continue
                return owner
        return None

    for comp in components_sorted:
        cid = comp["id"]
        cs = cands_by_id.get(cid, [])
        for cand in cs:
            owner = _conflicts(cand.start, cand.end)
            if owner is None:
                chosen[cid] = cand
                taken_ranges.append((cand.start, cand.end, cid))
                break
        else:
            # No non-conflicting candidate. Patent claims often
            # coordinate forms like "upper and lower parallel
            # extensions" where two components share most of the
            # surface form but differ on the discriminator ("upper"
            # vs "lower"). Accept the best candidate (lowest score)
            # even when overlapping with another component's range.
            if cs:
                cand = cs[0]  # already sorted by composite_score
                chosen[cid] = cand
                taken_ranges.append((cand.start, cand.end, cid))

    # Build result list in the original component order.
    result: list[RelocatedSpan] = []
    for comp in components:
        cid = comp["id"]
        claim_id = comp["source_span"]["claim_id"]
        text = claims_text_by_id.get(claim_id, "")
        if cid in chosen:
            cand = chosen[cid]
            result.append(
                RelocatedSpan(
                    component_id=cid,
                    claim_id=claim_id,
                    char_start=cand.start,
                    char_end=cand.end,
                    extracted=text[cand.start : cand.end],
                    matched_key=cand.key,
                    verified=True,
                    notes=f"matched '{cand.key}' at hint distance {cand.distance_from_hint}",
                )
            )
        else:
            # No match — leave clamped offsets and mark unverified.
            s = max(0, min(int(comp["source_span"]["char_start"]), len(text)))
            e = max(s, min(int(comp["source_span"]["char_end"]), len(text)))
            result.append(
                RelocatedSpan(
                    component_id=cid,
                    claim_id=claim_id,
                    char_start=s,
                    char_end=e,
                    extracted=text[s:e],
                    matched_key="",
                    verified=False,
                    notes="no key matched in claim text",
                )
            )
    return result


def write_span_debug(
    relocated: list[RelocatedSpan],
    components: list[dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write a markdown audit table for human inspection."""
    by_id = {c["id"]: c for c in components}
    lines: list[str] = ["# Span audit", ""]
    lines.append("| component_id | label | start | end | extracted | matched_key | verified |")
    lines.append("|---|---|---:|---:|---|---|---|")
    n_ok = 0
    for r in relocated:
        comp = by_id.get(r.component_id, {})
        label = comp.get("label", "")
        extracted_short = r.extracted[:60].replace("\n", " ")
        verified = "✓" if r.verified else "✗"
        if r.verified:
            n_ok += 1
        lines.append(
            f"| `{r.component_id}` | {label} | {r.char_start} | {r.char_end} "
            f"| `{extracted_short}` | `{r.matched_key}` | {verified} |"
        )
    lines.insert(2, f"\n**{n_ok}/{len(relocated)} verified.**\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote span audit %s (%d/%d verified)", out_path, n_ok, len(relocated))
    return out_path


__all__ = [
    "RelocatedSpan",
    "relocate_components",
    "write_span_debug",
]
