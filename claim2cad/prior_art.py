"""Prior-art comparison engine.

Given two ClaimIR objects (a *base* and a *comparison* / prior-art),
classify every component into one of three buckets:

- ``matched``: present in both (with a similarity score)
- ``novel_in_base``: present only in the base IR — the *novelty* over the
  prior art, in green
- ``only_in_comparison``: present only in the prior-art IR — what the
  prior art has that the base doesn't, in red

Two-pass matching:

1. **Cheap pass** — for each base component, find the best comparison
   component by ``SequenceMatcher`` similarity over labels (with kind
   matching as a bonus). Threshold 0.55.
2. **LLM disambiguation** — for the still-unmatched components, send
   both lists to Sonnet 4.6 and ask for a JSON pairing. Skipped when
   either list is empty or the cheap pass already mapped > 80 % of
   one side.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from claim2cad.ir_schema import ClaimIR, Component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cheap pairing
# ---------------------------------------------------------------------------


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _score_pair(a: Component, b: Component) -> float:
    sa = a.label.lower().strip()
    sb = b.label.lower().strip()
    ratio = _similarity(sa, sb)
    if sa in sb or sb in sa:
        ratio = max(ratio, 0.85)
    if a.kind == b.kind and a.kind:
        ratio = min(1.0, ratio + 0.05)
    if a.category == b.category:
        ratio = min(1.0, ratio + 0.02)
    return ratio


def _greedy_pair(
    base: list[Component], comparison: list[Component], *, threshold: float = 0.55
) -> tuple[list[tuple[str, str, float]], set[str], set[str]]:
    """Greedy bipartite matching by similarity score.

    Returns ``(pairs, unpaired_base_ids, unpaired_comparison_ids)`` where
    ``pairs`` is sorted descending by score.
    """
    candidates: list[tuple[float, str, str]] = []
    for a in base:
        for b in comparison:
            s = _score_pair(a, b)
            if s >= threshold:
                candidates.append((s, a.id, b.id))
    candidates.sort(reverse=True)

    used_base: set[str] = set()
    used_comp: set[str] = set()
    pairs: list[tuple[str, str, float]] = []
    for score, ba, bb in candidates:
        if ba in used_base or bb in used_comp:
            continue
        used_base.add(ba)
        used_comp.add(bb)
        pairs.append((ba, bb, round(score, 3)))

    unpaired_base = {a.id for a in base} - used_base
    unpaired_comp = {b.id for b in comparison} - used_comp
    return pairs, unpaired_base, unpaired_comp


# ---------------------------------------------------------------------------
# LLM disambiguation
# ---------------------------------------------------------------------------


_LLM_DISAMBIG_SYSTEM = """\
You match patent IR components across two patents to find prior-art
overlap.

You receive:
- A JSON list of components from PATENT A (the base claim).
- A JSON list of components from PATENT B (the prior-art comparison).
- A list of components in A that the cheap matcher could not pair.
- A list of components in B that the cheap matcher could not pair.

Return a single JSON object:
{"additional_pairs": [{"a_id": "...", "b_id": "...", "rationale": "...", "confidence": 0.0..1.0}]}

Rules:
- Only output pairs you are reasonably confident about (confidence ≥ 0.6).
- Each a_id maps to at most one b_id and vice versa.
- Do not output pairs already in the cheap-matcher result.
- It is fine to output an empty list if nothing else is matchable.
- Output exactly one JSON object — no prose, no fences.
"""


def _llm_disambiguate(
    base: list[Component],
    comparison: list[Component],
    unpaired_base: set[str],
    unpaired_comp: set[str],
    existing_pairs: list[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    """LLM-based disambiguation. Skipped on trivial inputs."""
    if not unpaired_base or not unpaired_comp:
        return []
    if len(unpaired_base) <= 1 and len(unpaired_comp) <= 1:
        return []

    from claim2cad.llm_client import json_completion

    def _row(c: Component) -> dict:
        return {
            "id": c.id,
            "label": c.label,
            "category": c.category,
            "kind": c.kind,
        }

    user_prompt = (
        "PATENT A components:\n"
        + json.dumps([_row(c) for c in base], indent=2)
        + "\n\nPATENT B components:\n"
        + json.dumps([_row(c) for c in comparison], indent=2)
        + "\n\nUnpaired in A: "
        + json.dumps(sorted(unpaired_base))
        + "\n\nUnpaired in B: "
        + json.dumps(sorted(unpaired_comp))
        + "\n\nExisting cheap-matcher pairs (do not duplicate): "
        + json.dumps([{"a_id": a, "b_id": b} for a, b, _ in existing_pairs])
        + "\n\nReturn the additional_pairs JSON."
    )
    try:
        body = json_completion(
            system_prompt=_LLM_DISAMBIG_SYSTEM,
            user_prompt=user_prompt,
            task_type="prior_art_diff",
            max_retries=2,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM disambiguation failed: %s", exc)
        return []

    out: list[tuple[str, str, float]] = []
    used_base = {a for a, _, _ in existing_pairs}
    used_comp = {b for _, b, _ in existing_pairs}
    for entry in body.get("additional_pairs", []) or []:
        a = entry.get("a_id")
        b = entry.get("b_id")
        conf = float(entry.get("confidence", 0.0) or 0.0)
        if a in unpaired_base and b in unpaired_comp and a not in used_base and b not in used_comp:
            if conf < 0.6:
                continue
            out.append((a, b, round(conf, 3)))
            used_base.add(a)
            used_comp.add(b)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class PriorArtDiff:
    base_patent: str
    comparison_patent: str
    matched: list[dict] = field(default_factory=list)
    novel_in_base: list[dict] = field(default_factory=list)
    only_in_comparison: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def diff_irs(
    base_ir: ClaimIR,
    comparison_ir: ClaimIR,
    *,
    base_label: str = "base",
    comparison_label: str = "comparison",
    use_llm: bool = True,
) -> PriorArtDiff:
    """Compute the prior-art diff between two IRs."""
    base_components = list(base_ir.components)
    comp_components = list(comparison_ir.components)

    pairs, unp_a, unp_b = _greedy_pair(base_components, comp_components)
    notes: list[str] = []
    if use_llm and unp_a and unp_b:
        extra = _llm_disambiguate(base_components, comp_components, unp_a, unp_b, pairs)
        if extra:
            for a, b, score in extra:
                pairs.append((a, b, score))
                unp_a.discard(a)
                unp_b.discard(b)
            notes.append(f"llm_added_pairs: {len(extra)}")

    base_by_id = {c.id: c for c in base_components}
    comp_by_id = {c.id: c for c in comp_components}

    matched_rows: list[dict] = []
    for a, b, score in pairs:
        ca = base_by_id[a]
        cb = comp_by_id[b]
        matched_rows.append({
            "base_id": a,
            "base_label": ca.label,
            "comparison_id": b,
            "comparison_label": cb.label,
            "score": score,
            "category": ca.category,
            "kind_base": ca.kind,
            "kind_comparison": cb.kind,
        })

    novel_rows = [
        {
            "id": cid,
            "label": base_by_id[cid].label,
            "category": base_by_id[cid].category,
            "kind": base_by_id[cid].kind,
        }
        for cid in sorted(unp_a)
    ]
    only_in_comp_rows = [
        {
            "id": cid,
            "label": comp_by_id[cid].label,
            "category": comp_by_id[cid].category,
            "kind": comp_by_id[cid].kind,
        }
        for cid in sorted(unp_b)
    ]

    return PriorArtDiff(
        base_patent=base_label,
        comparison_patent=comparison_label,
        matched=matched_rows,
        novel_in_base=novel_rows,
        only_in_comparison=only_in_comp_rows,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Filesystem-based driver
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent


def _example_id_from_dir(d: Path) -> str:
    return d.name


def _load_ir(d: Path) -> ClaimIR:
    return ClaimIR.model_validate_json((d / "claim_ir.json").read_text(encoding="utf-8"))


def diff_directories(
    base_dir: Path, comparison_dir: Path, *, use_llm: bool = True
) -> PriorArtDiff:
    base_ir = _load_ir(base_dir)
    comp_ir = _load_ir(comparison_dir)
    return diff_irs(
        base_ir,
        comp_ir,
        base_label=_example_id_from_dir(base_dir),
        comparison_label=_example_id_from_dir(comparison_dir),
        use_llm=use_llm,
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="claim2cad.prior_art")
    p.add_argument("--base", type=Path, required=True,
                   help="Path to the base example directory.")
    p.add_argument("--compare", type=Path, required=True,
                   help="Path to the prior-art comparison example directory.")
    p.add_argument("--out", type=Path, default=None,
                   help="Optional path to write the diff JSON. "
                        "Defaults to the base directory's "
                        "diff_<comparison_id>.json.")
    p.add_argument("--no-llm", action="store_true")
    args = p.parse_args(argv)

    logging.getLogger("claim2cad").setLevel(logging.INFO)

    diff = diff_directories(args.base, args.compare, use_llm=not args.no_llm)
    out_path = args.out or args.base / f"diff_{_example_id_from_dir(args.compare)}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(diff.as_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "base": diff.base_patent,
        "comparison": diff.comparison_patent,
        "matched": len(diff.matched),
        "novel_in_base": len(diff.novel_in_base),
        "only_in_comparison": len(diff.only_in_comparison),
        "out": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PriorArtDiff",
    "diff_directories",
    "diff_irs",
]
