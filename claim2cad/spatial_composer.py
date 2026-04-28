"""Spatial composer — one VLM call to align every component in the assembly.

The figure-to-spec pass picks library parts and codegen for each component
in isolation. Each component therefore arrives with its own internal
coordinate frame and a guess at where it should sit. Those guesses rarely
make the assembly *physically work*: the pintle pin doesn't always thread
through all the side holes, the leaf flange doesn't always sit against
the link member, the U-bracket open faces don't always point the right way.

This module fixes that with a single Opus 4.7 call that sees:

  * the full patent figure(s),
  * the current rendered assembly,
  * each component's bounding box and label.

…and emits a complete set of (position_mm, rotation_deg) revisions so
shared axes line up. It treats geometry as immutable — only pose changes.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import build123d as bd

from claim2cad.figure_to_cad import ComponentSpec, FigureSpec
from claim2cad.llm_vision import vision_completion
from claim2cad.visual_validator import make_comparison_grid

logger = logging.getLogger(__name__)


@dataclass
class ComponentBBox:
    """Per-component bbox shipped to the VLM for spatial reasoning."""

    component_id: str
    library_part: str | None
    notes: str
    size_mm: tuple[float, float, float]
    current_position_mm: tuple[float, float, float]
    current_rotation_deg: tuple[float, float, float]
    constraints: list[str]


_SYSTEM_PROMPT = (
    "You are arranging a CAD assembly so it matches the spatial relationships "
    "in a patent drawing. You will see the patent figure on the left and the "
    "candidate assembly's current rendered state on the right. For every "
    "component listed, decide a NEW position_mm and rotation_deg so the "
    "claim relationships hold (pins thread through aligned holes; brackets "
    "with U-channels open toward what nests inside them; mounting plates "
    "sit flat against what they mount to). Geometry is fixed — only poses "
    "change. Return strict JSON."
)


_USER_TEMPLATE = """Patent context: {patent_context}

Claim relations (verbatim from the IR):
{relations}

Each component below has a bbox (size in mm), its current pose, the
library_part / codegen tag that built it, and any claim constraints
naming it. Re-pose every component so the assembly *actually works*:
  - if a pin "passes through" multiple components, the pin's central
    axis must pierce each component's hole region;
  - if a U-bracket carries an inner link, the inner link's axis must
    line up with the U-bracket's hole axis;
  - if a leaf flange "abuts" a sidewall, their faces must touch;
  - keep the whole assembly inside roughly a 200 mm cube centred on origin.

Components:
{components_block}

Return JSON in this EXACT shape:
{{
  "poses": [
    {{
      "component_id": "<must match an id below>",
      "position_mm": [<x>, <y>, <z>],
      "rotation_deg": [<rx>, <ry>, <rz>]
    }},
    ...
  ],
  "explanation": "<2-3 sentences on the assembly logic you applied>"
}}

Cover EVERY component_id listed. Coordinates in mm. No math expressions.
"""


def _components_block(rows: list[ComponentBBox]) -> str:
    out: list[str] = []
    for r in rows:
        sx, sy, sz = r.size_mm
        px, py, pz = r.current_position_mm
        rx, ry, rz = r.current_rotation_deg
        out.append(
            f"  - id={r.component_id} | source={r.library_part or 'codegen'} | "
            f"size_mm=({sx:.1f},{sy:.1f},{sz:.1f}) | "
            f"current_pos=({px:.1f},{py:.1f},{pz:.1f}) | "
            f"current_rot=({rx:.1f},{ry:.1f},{rz:.1f})"
        )
        if r.constraints:
            cs = "; ".join(r.constraints)[:200]
            out.append(f"      claim: {cs}")
        if r.notes:
            out.append(f"      notes: {r.notes[:160]}")
    return "\n".join(out)


def _bboxes_for_assembly(
    spec: FigureSpec,
    component_solids: dict[str, bd.Part | bd.Compound],
    ir_constraints: dict[str, list[str]],
) -> list[ComponentBBox]:
    rows: list[ComponentBBox] = []
    for s in spec.components:
        solid = component_solids.get(s.component_id)
        if solid is None:
            continue
        bb = solid.bounding_box()
        rows.append(
            ComponentBBox(
                component_id=s.component_id,
                library_part=s.library_part,
                notes=s.notes,
                size_mm=(bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z),
                current_position_mm=tuple(s.position_mm),  # type: ignore[arg-type]
                current_rotation_deg=tuple(s.rotation_deg),  # type: ignore[arg-type]
                constraints=ir_constraints.get(s.component_id, []),
            )
        )
    return rows


def _format_relations(relations: list[Any]) -> str:
    if not relations:
        return "  (none)"
    out: list[str] = []
    for r in relations[:30]:
        kind = getattr(r, "kind", None) or (r.get("kind") if isinstance(r, dict) else "?")
        src = getattr(r, "source", None) or (r.get("source") if isinstance(r, dict) else "?")
        tgt = getattr(r, "target", None) or (r.get("target") if isinstance(r, dict) else "?")
        out.append(f"  - {src} --[{kind}]--> {tgt}")
    return "\n".join(out)


def compose_spatial(
    *,
    spec: FigureSpec,
    component_solids: dict[str, bd.Part | bd.Compound],
    figure_path: Path,
    rendered_pngs: list[Path],
    ir_constraints: dict[str, list[str]],
    relations: list[Any],
    composite_path: Path,
    patent_context: str = "",
    task_type: str = "v11_spatial_composer",
) -> tuple[FigureSpec, str]:
    """Run the spatial composer pass. Returns (revised_spec, explanation).

    The composite image (figure | renders grid) is the SAME image the
    validator uses, so the VLM is judging against the very rendered state
    it's revising.
    """
    composite = make_comparison_grid(
        rendered_pngs, figure_path, composite_path, label_left="Patent figure", label_right="Current assembly"
    )
    rows = _bboxes_for_assembly(spec, component_solids, ir_constraints)
    if not rows:
        logger.warning("Spatial composer: no buildable components — skipping")
        return spec, "no components to compose"
    prompt = _USER_TEMPLATE.format(
        patent_context=patent_context or "(none)",
        relations=_format_relations(relations),
        components_block=_components_block(rows),
    )
    raw = vision_completion(
        image_path=composite,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=prompt,
        task_type=task_type,
    )
    poses = raw.get("poses") or []
    explanation = str(raw.get("explanation", ""))
    if not isinstance(poses, list) or not poses:
        logger.warning("Spatial composer returned no poses")
        return spec, explanation or "no poses returned"

    # Apply poses — keep everything else as-is.
    by_id = {s.component_id: s for s in spec.components}
    n_applied = 0
    for p in poses:
        if not isinstance(p, dict):
            continue
        cid = str(p.get("component_id", "")).strip()
        existing = by_id.get(cid)
        if existing is None:
            continue
        try:
            pos = tuple(float(v) for v in p.get("position_mm", existing.position_mm))[:3]
            if len(pos) < 3:
                pos = pos + (0.0,) * (3 - len(pos))
        except (TypeError, ValueError):
            pos = existing.position_mm
        try:
            rot = tuple(float(v) for v in p.get("rotation_deg", existing.rotation_deg))[:3]
            if len(rot) < 3:
                rot = rot + (0.0,) * (3 - len(rot))
        except (TypeError, ValueError):
            rot = existing.rotation_deg
        by_id[cid] = ComponentSpec(
            component_id=cid,
            library_part=existing.library_part,
            params=existing.params,
            position_mm=pos,  # type: ignore[arg-type]
            rotation_deg=rot,  # type: ignore[arg-type]
            features=existing.features,
            notes=existing.notes,
        )
        n_applied += 1
    logger.info(
        "Spatial composer applied %d/%d pose revisions: %s",
        n_applied,
        len(poses),
        explanation[:160],
    )
    revised = FigureSpec(
        patent_id=spec.patent_id,
        figure_id=spec.figure_id,
        components=list(by_id.values()),
        raw=spec.raw,
    )
    return revised, explanation


__all__ = ["ComponentBBox", "compose_spatial"]
