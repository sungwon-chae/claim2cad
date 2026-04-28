"""IR enricher — augment claim_ir.json with sub-features visible in the
patent figure but not named by the claim text.

The claim text only names the components legally claimed. The figure
shows many more features (numbered fasteners, sub-flanges, retention
shoulders, alignment guides). Those features explain a lot of the
silhouette difference between the patent figure and our v1.1 CAD.

Pipeline: read figure_map.json, find numbered callouts NOT bound to any
IR component, send the figure crop + the figure_map context to the VLM,
ask it to classify each unmapped number into one of:

  * sub-feature of an existing IR component (skip — already covered)
  * standalone small geometric feature (proposed as a new component)
  * label / dimension / detail (skip)

For each "standalone small geometric feature" the VLM emits a one-line
geometric description (e.g. "small cylindrical pin head 6mm × 3mm")
that the codegen path can build.

The output is a list of new ComponentSpecs that get spliced into the
existing FigureSpec before the spatial composer runs.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from claim2cad.figure_to_cad import ComponentSpec, FigureSpec
from claim2cad.figure_crops import FigureCrop
from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are extending a parametric CAD assembly to cover MORE of the "
    "patent figure than the claim text named. You will see the patent "
    "figure and a list of numbered callouts that the claim IR did NOT "
    "bind to any component. For each unmapped number, decide whether it "
    "deserves its own small CAD component, and if so, describe its "
    "shape concisely. Always return strict JSON."
)

_USER_TEMPLATE = """Patent context: {patent_context}

The IR already covers these components (by their figure number):
{covered_numbers}

These figure-number callouts are NOT yet covered. For each, tell us
whether to skip it (it is already part of one of the covered
components, or it is a label/dimension/arrow only) or to add a small
new geometry. When adding, give a one-line `shape` description and
which CLAIM component it should attach to (parent_id) or "world".

Unmapped callouts:
{unmapped_block}

Return JSON in this EXACT shape:
{{
  "additions": [
    {{
      "figure_number": "<the callout number, as string>",
      "proposed_component_id": "<short snake_case id>",
      "label": "<human-readable label>",
      "kind": "<sub-feature|fastener|stop|guide|hole|other>",
      "parent_id": "<existing IR component id or null>",
      "shape": "<short build123d-friendly geometry hint, e.g. 'small cylindrical pin head 6mm dia 3mm tall' or 'oblong slot 12x4x3'>",
      "approximate_position_xy_norm": [<x>, <y>]
    }}
  ],
  "skipped": [
    {{ "figure_number": "<...>", "reason": "<short>" }}
  ]
}}

Rules:
- Add at MOST 8 features. Pick the ones with clearest standalone geometry.
- Use mm. Keep each addition's overall extent under ~30mm.
- Skip pure labels, dimension lines, arrowheads, and centerline marks.
"""


def enrich_ir(
    *,
    figure_path: Path,
    figure_map: dict[str, Any],
    spec: FigureSpec,
    patent_context: str = "",
    task_type: str = "v11_ir_enrich",
) -> tuple[list[ComponentSpec], list[dict[str, Any]]]:
    """Return (new_specs, skipped_rows). Caller splices new_specs into the
    main FigureSpec and the IR before the next build pass."""
    component_to_number = figure_map.get("component_to_number", {}) or {}
    covered = sorted(set(map(str, component_to_number.values())))
    labels = figure_map.get("vlm_labels", []) or []
    all_label_numbers = sorted({str(l.get("number", "")).strip() for l in labels if l.get("number")})
    unmapped = [n for n in all_label_numbers if n not in covered]
    if not unmapped:
        logger.info("IR enricher: nothing unmapped — skipping")
        return [], []

    # Position lookup
    pos_for: dict[str, tuple[float, float]] = {}
    for l in labels:
        n = str(l.get("number", "")).strip()
        p = l.get("approximate_position", [])
        if n and len(p) >= 2:
            pos_for[n] = (float(p[0]), float(p[1]))

    rows: list[str] = []
    for n in unmapped:
        x, y = pos_for.get(n, (0.5, 0.5))
        rows.append(f"  - fig#{n} at ({x:.2f}, {y:.2f})")

    user_prompt = _USER_TEMPLATE.format(
        patent_context=patent_context or "(none)",
        covered_numbers=", ".join(covered),
        unmapped_block="\n".join(rows),
    )
    raw = vision_completion(
        image_path=figure_path,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        task_type=task_type,
    )
    additions = raw.get("additions") or []
    skipped = raw.get("skipped") or []
    new_specs: list[ComponentSpec] = []
    seen_ids = {s.component_id for s in spec.components}
    for a in additions:
        if not isinstance(a, dict):
            continue
        cid = str(a.get("proposed_component_id") or "").strip()
        if not cid:
            continue
        # Avoid id clash with existing components.
        base = cid
        i = 2
        while cid in seen_ids:
            cid = f"{base}_{i}"
            i += 1
        seen_ids.add(cid)
        shape = str(a.get("shape", ""))
        kind = str(a.get("kind", "other"))
        new_specs.append(
            ComponentSpec(
                component_id=cid,
                library_part=None,
                params={},
                position_mm=(0.0, 0.0, 0.0),
                rotation_deg=(0.0, 0.0, 0.0),
                features=[shape, f"figure_number={a.get('figure_number')}", f"kind={kind}"],
                notes=f"codegen — IR-enrichment from figure number {a.get('figure_number')}: {shape}",
            )
        )
    logger.info(
        "IR enricher: proposed %d additions, %d skipped (%d unmapped total)",
        len(new_specs),
        len(skipped),
        len(unmapped),
    )
    return new_specs, list(skipped)


def merge_into_spec(spec: FigureSpec, additions: list[ComponentSpec]) -> FigureSpec:
    """Splice ``additions`` into the spec's component list."""
    if not additions:
        return spec
    return FigureSpec(
        patent_id=spec.patent_id,
        figure_id=spec.figure_id,
        components=list(spec.components) + list(additions),
        raw=spec.raw,
    )


__all__ = ["enrich_ir", "merge_into_spec"]
