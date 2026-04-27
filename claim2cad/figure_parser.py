"""Patent figure parsing.

Strategy (V1-3):

1. **Text-first.** US patent claims reference numbered components inline,
   e.g. "a base 10, a first link 20 attached to said base 10". A regex
   pulls every ``<noun phrase> <number>`` pair out of the claim text.
   This produces (claim_phrase, number) tuples without any LLM call.
2. **VLM enrichment.** A vision call to ``llm_vision.vision_completion``
   on the patent's primary figure returns ``[{"number", "description",
   "approximate_position"}]``. We use this to:
   - confirm which numbers actually appear on the drawing
   - capture a short description for hover tooltips
   - get a normalised bounding box for the viewer's hotspots
3. **Merge.** ``merge_with_ir(figure_map, ir)`` walks the IR's
   components, finds the best matching ``claim_phrase`` for each
   component (exact / substring / fuzzy), and stamps
   ``Component.figure_number`` and ``Component.figure_references``
   accordingly.

The text-first pass means a working ``figure_map.json`` is producible
even when the VLM fails or no figure exists.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from claim2cad.ir_schema import ClaimIR, Component, FigureReference

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text-first extraction
# ---------------------------------------------------------------------------


# Match patterns like:
#   "a base 10"
#   "the first link 20"
#   "a coupler member, indicated as 30"
#   "an output portion (40)"
# Constraint: number is 1–4 digits, follows a noun phrase up to ~5 words.
_NUMBERED_PHRASE_RE = re.compile(
    r"""
    (?:                                  # leading article variants
       \b(?:a|an|the|said|each)\s+
    )?
    (
        [a-z][a-z\-]+                    # head noun word(s) — letters / hyphen
        (?:\s+[a-z][a-z\-]+){0,4}         # up to 4 more words
    )
    [\s,]*                                # optional comma + spaces
    (?:indicated\s+as\s+|labeled\s+|labelled\s+|reference\s+numeral\s+|numbered\s+)?
    (?:\(|\b)                             # optional opening paren or word boundary
    (\d{1,4})                             # the number itself
    (?:\)|\b)                             # optional closing paren or word boundary
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Words we never want to grab as a phrase head (claim boilerplate / verbs).
_PHRASE_BLOCKLIST = {
    "claim", "claims", "comprising", "wherein", "having", "whereby",
    "including", "consists", "consisting", "characterized", "providing",
    "comprises", "for", "to", "of", "and", "or", "with", "by", "via",
    "between", "from", "the",
}


@dataclass
class NumberedPhrase:
    phrase: str          # noun phrase as it appeared in the claim
    number: str          # stringified component number from the claim
    char_start: int
    char_end: int

    def as_dict(self) -> dict:
        return {
            "phrase": self.phrase,
            "number": self.number,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


def extract_numbered_phrases(claim_text: str) -> list[NumberedPhrase]:
    """Pure-regex pass over the claim text. Returns one entry per
    ``<phrase> <number>`` pair, deduplicated on (phrase, number)."""
    seen: dict[tuple[str, str], NumberedPhrase] = {}
    for match in _NUMBERED_PHRASE_RE.finditer(claim_text):
        phrase = match.group(1).strip().lower()
        number = match.group(2)
        first_word = phrase.split()[0]
        if first_word in _PHRASE_BLOCKLIST:
            continue
        # Drop "claim 1" / "claim 12" — those are claim references, not parts.
        if first_word == "claim" or "claim" in phrase.split():
            continue
        # Drop pure-digit number contexts ("for 24 hours", "after 3 minutes").
        # Heuristic: if the matched phrase is just "a" or "the" alone, skip.
        if len(phrase) < 3:
            continue
        key = (phrase, number)
        if key in seen:
            continue
        seen[key] = NumberedPhrase(
            phrase=phrase,
            number=number,
            char_start=match.start(1),
            char_end=match.end(2),
        )
    out = list(seen.values())
    out.sort(key=lambda p: p.char_start)
    return out


# ---------------------------------------------------------------------------
# VLM call
# ---------------------------------------------------------------------------


_VLM_SYSTEM_PROMPT = """\
You are a patent-figure analyser. Given an image of a US-patent figure,
return a single JSON object describing every numbered component label
visible on the drawing.

Rules:
- Only return labels that are explicitly drawn on the figure with a number
  (1-4 digits) typically connected to a part by a leadline.
- Skip figure titles, axis labels, dimension callouts, and equation
  numbers.
- "approximate_position" is an array [x, y] in normalised image
  coordinates (0..1, with origin at top-left).
- "bbox" (optional) is [x, y, w, h] in the same coordinates.
- Output exactly one JSON object. No prose, no markdown fences.
"""

_VLM_USER_PROMPT = """\
Return JSON of the form:
{
  "labels": [
    {"number": "10", "description": "rectangular base", "approximate_position": [0.5, 0.85], "bbox": [0.45, 0.80, 0.10, 0.10]},
    ...
  ]
}
"""


def analyze_figure(image_path: Path) -> dict[str, Any]:
    """VLM call. Returns ``{"labels": [...]}`` or raises LLMResponseError.
    Wrapped here so callers can swap the implementation in tests."""
    from claim2cad.llm_vision import vision_completion  # local import to keep this module light

    return vision_completion(
        image_path=image_path,
        system_prompt=_VLM_SYSTEM_PROMPT,
        user_prompt=_VLM_USER_PROMPT,
        task_type="vision_figure_parse",
    )


# Cheap text-only re-match using Sonnet. The rule-based matcher catches
# obvious cases ("ring gear" ↔ "ring gear") but misses ones where the VLM's
# description is more generic than the IR's label ("gear" ↔ "first planet
# pinion"). The text-only call resolves these by reasoning about all
# components + labels jointly.
_REMATCH_SYSTEM_PROMPT = """\
You match patent IR components to figure labels.

You are given:
- A JSON list of IR components (id + human label).
- A JSON list of figure labels extracted from a patent drawing
  (number + short description).

Return one JSON object: {"mappings": [{"component_id": "...", "number": "..."}]}

Rules:
- Each component_id maps to at most one number.
- Each number maps to at most one component_id.
- It is OK to leave components unmapped — only output mappings you are
  confident about.
- Numbers must be strings as they appeared in the input.
- Output exactly one JSON object. No prose, no fences.
"""


def llm_rematch(
    components: list[Component], vlm_labels: list[dict]
) -> dict[str, str]:
    """Ask the LLM to jointly assign IR components to VLM-extracted numbers.

    Cheap (~$0.03 per call) and substantially boosts mapping coverage
    because the LLM can reason globally instead of matching one component
    at a time.
    """
    from claim2cad.llm_client import json_completion

    if not components or not vlm_labels:
        return {}

    components_payload = [{"id": c.id, "label": c.label, "kind": c.kind} for c in components]
    labels_payload = [
        {
            "number": str(lbl.get("number", "")),
            "description": lbl.get("description", ""),
        }
        for lbl in vlm_labels
        if str(lbl.get("number", "")).isdigit()
    ]
    user_prompt = (
        "Components:\n"
        + json.dumps(components_payload, indent=2)
        + "\n\nFigure labels:\n"
        + json.dumps(labels_payload, indent=2)
        + "\n\nReturn the mappings JSON."
    )
    try:
        body = json_completion(
            system_prompt=_REMATCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            task_type="figure_rematch",
            max_retries=2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_rematch failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for entry in body.get("mappings", []) or []:
        cid = entry.get("component_id")
        num = str(entry.get("number", "")).strip()
        if cid and num.isdigit():
            out[cid] = num
    return out


# ---------------------------------------------------------------------------
# Matching claim phrases / VLM labels → IR components
# ---------------------------------------------------------------------------


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_phrase_for(component: Component, phrases: list[NumberedPhrase]) -> Optional[NumberedPhrase]:
    """Pick the phrase whose label best matches the component."""
    best: Optional[NumberedPhrase] = None
    best_score = 0.0
    label = component.label.lower().strip()
    for p in phrases:
        # Strong signal: component span overlaps phrase span.
        if (
            component.source_span.char_start <= p.char_end
            and component.source_span.char_end >= p.char_start
        ):
            score = 1.0
        else:
            score = _similarity(label, p.phrase)
            # Bonus if phrase is a substring of label or vice versa.
            if label in p.phrase or p.phrase in label:
                score = max(score, 0.85)
        if score > best_score and score >= 0.55:
            best_score = score
            best = p
    return best


def _best_vlm_label_for(
    component: Component, vlm_labels: list[dict]
) -> Optional[dict]:
    """Pick the VLM label whose description best matches the component label.

    Most US-patent claim *claims* don't include figure numbers — those live
    in the specification text. So when the regex pass yields no
    ``NumberedPhrase``, we fall back to matching the IR component's label
    against the VLM-extracted description (e.g. component "ring_gear" with
    label "ring gear" ↔ VLM label `{description: "ring gear", number: "18"}`).

    Returns the matching VLM label dict (with ``number``, ``description``,
    optional ``bbox``/``approximate_position``), or None.
    """
    label = component.label.lower().strip()
    label_words = {w for w in re.split(r"[^a-z0-9]+", label) if len(w) >= 3}
    best: Optional[dict] = None
    best_score = 0.0
    for vl in vlm_labels:
        desc = str(vl.get("description", "")).lower().strip()
        if not desc:
            continue
        score = _similarity(label, desc)
        # Substring boost.
        if label in desc or desc in label:
            score = max(score, 0.85)
        # Word-overlap boost (e.g. "first ring gear" vs. "ring gear").
        desc_words = {w for w in re.split(r"[^a-z0-9]+", desc) if len(w) >= 3}
        overlap = label_words & desc_words
        if overlap:
            score = max(score, 0.5 + 0.15 * len(overlap))
        if score > best_score and score >= 0.55:
            best_score = score
            best = vl
    return best


@dataclass
class FigureMap:
    schema_version: str = "0.1.0"
    patent_id: str = ""
    primary_figure: Optional[str] = None  # filename, e.g. "figure_1.png"
    numbered_phrases: list[dict] = field(default_factory=list)
    vlm_labels: list[dict] = field(default_factory=list)
    component_to_number: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "patent_id": self.patent_id,
            "primary_figure": self.primary_figure,
            "numbered_phrases": self.numbered_phrases,
            "vlm_labels": self.vlm_labels,
            "component_to_number": self.component_to_number,
            "notes": self.notes,
        }


def merge_with_ir(figure_map: FigureMap, ir: ClaimIR) -> ClaimIR:
    """Stamp each IR component with figure_number / figure_references
    based on the figure_map's resolved component_to_number table."""
    figure_id = (figure_map.primary_figure or "figure_1").rsplit(".", 1)[0]
    bbox_by_number: dict[str, list[float]] = {}
    for label in figure_map.vlm_labels:
        n = str(label.get("number", "")).strip()
        bbox = label.get("bbox") or label.get("approximate_position")
        if n and bbox:
            # Normalise to [x, y, w, h]; if only [x, y] given we synthesise a
            # tiny bbox so the viewer still has a hotspot.
            if isinstance(bbox, list) and len(bbox) == 2:
                bbox = [float(bbox[0]) - 0.02, float(bbox[1]) - 0.02, 0.04, 0.04]
            bbox_by_number[n] = [float(v) for v in bbox][:4]

    new_components: list[Component] = []
    for comp in ir.components:
        number = figure_map.component_to_number.get(comp.id)
        if not number:
            new_components.append(comp)
            continue
        refs = list(comp.figure_references)
        if number in bbox_by_number:
            refs.append(FigureReference(figure_id=figure_id, bbox=bbox_by_number[number]))
        else:
            refs.append(FigureReference(figure_id=figure_id))
        new_components.append(comp.model_copy(update={
            "figure_number": number,
            "figure_references": refs,
        }))

    return ir.model_copy(update={"components": new_components})


# ---------------------------------------------------------------------------
# End-to-end on a patent directory
# ---------------------------------------------------------------------------


def process_patent_directory(
    patent_dir: Path,
    *,
    use_vlm: bool = True,
) -> Optional[FigureMap]:
    """Run figure parsing on one patent directory. Writes
    ``figure_map.json`` next to the IR and updates ``claim_ir.json`` and
    ``claim_map.json`` to include figure references.

    Returns the FigureMap on success, None if no claim+IR pair exists.
    """
    claim_path = patent_dir / "claim.txt"
    ir_path = patent_dir / "claim_ir.json"
    if not (claim_path.exists() and ir_path.exists()):
        logger.warning("Skipping %s: missing claim or IR", patent_dir.name)
        return None

    claim_text = claim_path.read_text(encoding="utf-8")
    ir = ClaimIR.model_validate_json(ir_path.read_text(encoding="utf-8"))

    metadata_path = patent_dir / "source_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    patent_id = metadata.get("patent_id", patent_dir.name.split("_", 1)[0])

    fmap = FigureMap(patent_id=patent_id)

    # 1. Text-first numbered phrases
    phrases = extract_numbered_phrases(claim_text)
    fmap.numbered_phrases = [p.as_dict() for p in phrases]
    if not phrases:
        fmap.notes.append("no_numbered_phrases_in_claim")

    # 2. VLM analysis on the first figure
    figures_dir = patent_dir / "figures"
    primary: Optional[Path] = None
    for cand in ("figure_1.png", "figure_1.jpg", "figure_1.gif", "figure_1.tif"):
        p = figures_dir / cand
        if p.exists() and p.stat().st_size > 1024:
            primary = p
            break
    if primary is None:
        # Fall back to any figure file.
        if figures_dir.exists():
            for p in sorted(figures_dir.glob("figure_*.*")):
                if p.stat().st_size > 1024:
                    primary = p
                    break
    if primary:
        fmap.primary_figure = primary.name
        if use_vlm:
            try:
                vlm_response = analyze_figure(primary)
                fmap.vlm_labels = list(vlm_response.get("labels", []))[:60]
            except Exception as exc:  # noqa: BLE001
                logger.warning("VLM failed for %s: %s", patent_dir.name, exc)
                fmap.notes.append(f"vlm_error: {type(exc).__name__}")
    else:
        fmap.notes.append("no_figure_image_available")

    # 3. Match to IR components.
    #    Pass A: regex-based numbered-phrase match (older patents with
    #    inline numbers).
    #    Pass B: rule-based matcher against VLM descriptions (cheap,
    #    catches obvious "ring gear" ↔ "ring gear" cases).
    #    Pass C: LLM-based re-match for components still unmatched. This
    #    is the only pass that handles ambiguous cases like three
    #    "planet pinion" components in the IR vs. four "gear" labels on
    #    the figure.
    component_to_number: dict[str, str] = {}
    used_vlm_indices: set[int] = set()

    if phrases:
        for component in ir.components:
            match_phrase = _best_phrase_for(component, phrases)
            if match_phrase is not None:
                component_to_number[component.id] = match_phrase.number

    if fmap.vlm_labels:
        for component in ir.components:
            if component.id in component_to_number:
                continue
            vlm_match = _best_vlm_label_for(component, fmap.vlm_labels)
            if vlm_match is None:
                continue
            idx = fmap.vlm_labels.index(vlm_match)
            if idx in used_vlm_indices:
                continue
            used_vlm_indices.add(idx)
            number = str(vlm_match.get("number", "")).strip()
            if number.isdigit():
                component_to_number[component.id] = number

    # Pass C — LLM rematch for components still unmapped, but only if it
    # would meaningfully improve coverage.
    unmapped = [c for c in ir.components if c.id not in component_to_number]
    if fmap.vlm_labels and unmapped and len(unmapped) >= 2:
        rematch = llm_rematch(unmapped, fmap.vlm_labels)
        used_numbers = set(component_to_number.values())
        for cid, number in rematch.items():
            # Don't overwrite earlier matches; don't double-claim numbers.
            if cid in component_to_number:
                continue
            if number in used_numbers:
                continue
            component_to_number[cid] = number
            used_numbers.add(number)

    fmap.component_to_number = component_to_number

    # 4. Persist figure_map.json
    fmap_path = patent_dir / "figure_map.json"
    fmap_path.write_text(json.dumps(fmap.as_dict(), indent=2) + "\n", encoding="utf-8")
    logger.info(
        "Wrote %s (%d phrases, %d vlm labels, %d components mapped)",
        fmap_path,
        len(fmap.numbered_phrases),
        len(fmap.vlm_labels),
        len(fmap.component_to_number),
    )

    # 5. Update claim_ir.json with figure stamps
    enriched_ir = merge_with_ir(fmap, ir)
    ir_path.write_text(enriched_ir.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # 6. Mirror the figure_number into claim_map.json so the viewer reads it
    #    from a single file.
    cmap_path = patent_dir / "claim_map.json"
    if cmap_path.exists():
        cmap = json.loads(cmap_path.read_text(encoding="utf-8"))
        for row in cmap.get("components", []):
            number = component_to_number.get(row["component_id"])
            if number:
                row["figure_number"] = number
        cmap_path.write_text(json.dumps(cmap, indent=2) + "\n", encoding="utf-8")

    return fmap


def process_all(
    patents_root: Path, *, use_vlm: bool = True, limit: Optional[int] = None
) -> dict[str, Any]:
    """Drive ``process_patent_directory`` across every patent under
    ``patents_root``. Skips directories already containing
    ``figure_map.json`` unless ``CLAIM2CAD_FIGURE_REPROCESS=1``.

    Returns aggregate stats for the V1-3 report writer.
    """
    import os
    import time

    reprocess = os.environ.get("CLAIM2CAD_FIGURE_REPROCESS") == "1"
    rows: list[dict] = []
    patent_dirs = sorted(d for d in patents_root.iterdir()
                         if d.is_dir() and (d / "claim.txt").exists())
    if limit:
        patent_dirs = patent_dirs[:limit]

    for d in patent_dirs:
        existing = d / "figure_map.json"
        if existing.exists() and not reprocess:
            try:
                cached = json.loads(existing.read_text(encoding="utf-8"))
                rows.append({
                    "patent_id": cached.get("patent_id", d.name.split("_", 1)[0]),
                    "patent_dir": d.name,
                    "vlm_labels": len(cached.get("vlm_labels", [])),
                    "components_mapped": len(cached.get("component_to_number", {})),
                    "ir_components": len(json.loads((d / "claim_ir.json").read_text("utf-8")).get("components", [])),
                    "primary_figure": cached.get("primary_figure"),
                    "notes": cached.get("notes", []),
                    "cached": True,
                })
                logger.info("Cached %s: %d/%d mapped",
                            d.name,
                            len(cached.get("component_to_number", {})),
                            len(json.loads((d / "claim_ir.json").read_text("utf-8")).get("components", [])))
                continue
            except Exception:  # noqa: BLE001
                pass
        start = time.time()
        try:
            fmap = process_patent_directory(d, use_vlm=use_vlm)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Figure parse failed for %s", d.name)
            rows.append({
                "patent_id": d.name.split("_", 1)[0],
                "patent_dir": d.name,
                "vlm_labels": 0,
                "components_mapped": 0,
                "ir_components": 0,
                "primary_figure": None,
                "notes": [f"exception: {type(exc).__name__}"],
                "cached": False,
                "duration_s": round(time.time() - start, 2),
            })
            continue
        if fmap is None:
            rows.append({
                "patent_id": d.name.split("_", 1)[0],
                "patent_dir": d.name,
                "vlm_labels": 0,
                "components_mapped": 0,
                "ir_components": 0,
                "primary_figure": None,
                "notes": ["no_claim_or_ir"],
                "cached": False,
                "duration_s": round(time.time() - start, 2),
            })
            continue
        ir_n = len(json.loads((d / "claim_ir.json").read_text("utf-8")).get("components", []))
        rows.append({
            "patent_id": fmap.patent_id,
            "patent_dir": d.name,
            "vlm_labels": len(fmap.vlm_labels),
            "components_mapped": len(fmap.component_to_number),
            "ir_components": ir_n,
            "primary_figure": fmap.primary_figure,
            "notes": fmap.notes,
            "cached": False,
            "duration_s": round(time.time() - start, 2),
        })
    return {
        "patents": rows,
        "summary": {
            "total": len(rows),
            "with_vlm_labels": sum(1 for r in rows if r["vlm_labels"] > 0),
            "with_at_least_one_mapping": sum(1 for r in rows if r["components_mapped"] > 0),
            "with_full_mapping": sum(
                1 for r in rows
                if r["ir_components"] > 0 and r["components_mapped"] == r["ir_components"]
            ),
        },
    }


__all__ = [
    "FigureMap",
    "NumberedPhrase",
    "analyze_figure",
    "extract_numbered_phrases",
    "llm_rematch",
    "merge_with_ir",
    "process_all",
    "process_patent_directory",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(prog="claim2cad.figure_parser")
    p.add_argument("--patents-dir", type=Path,
                   default=Path(__file__).resolve().parent.parent / "examples" / "real_patents")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-vlm", action="store_true",
                   help="Skip VLM call; text-first only.")
    p.add_argument("--report", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    import logging as _logging
    _logging.getLogger("claim2cad").setLevel(_logging.INFO)
    args = _build_arg_parser().parse_args(argv)
    result = process_all(args.patents_dir, use_vlm=not args.no_vlm, limit=args.limit)
    if args.report:
        print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
