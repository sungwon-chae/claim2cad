"""2D outline polygon → 2.5D extruded solid via build123d.

Companion to ``claim2cad.figure_to_sketch``. Takes a
``ComponentOutline`` (polygon in normalised figure coordinates +
extrusion depth + z offset) and returns a build123d ``Part`` whose
**top-down silhouette equals the polygon as drawn in the patent
figure** — which is the whole point.

Coordinate convention:

  * Figure normalised coords: ``(x, y)`` in [0, 1], origin **top-left**,
    y growing downward (standard image convention).
  * CAD world coords: X to the right, Y *up* (we flip y), Z out of the
    page. So an outline traced on the figure becomes a flat profile in
    the X-Y plane that we then extrude in +Z.
  * The whole figure is anchored to the world origin: its centre is at
    (0, 0, 0). Each component's polygon is rescaled by
    ``figure_scale_mm / longest_axis_norm`` and centred relative to the
    figure centre.

This means the orthographic *top* view of the resulting CAD looks
exactly like the original figure (modulo the z-stack). That's the
"figure first, depth second" approach the user asked for.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

import build123d as bd

from claim2cad.figure_to_sketch import ComponentOutline, OutlineSet

logger = logging.getLogger(__name__)


@dataclass
class ExtrusionResult:
    """Output of building one component."""

    component_id: str
    solid: bd.Part | bd.Compound | None
    bbox_mm: tuple[float, float, float] | None = None
    notes: str = ""
    diagnostics: list[str] = field(default_factory=list)


def _norm_to_world_xy(
    pts: Iterable[tuple[float, float]],
    *,
    figure_scale_mm: float,
    aspect: float,
) -> list[tuple[float, float]]:
    """Map normalised (x, y) ∈ [0, 1] (origin top-left, y down) into mm
    world coordinates centred on origin (origin centre, y up)."""
    # The longest axis of the figure represents `figure_scale_mm` in
    # the real world. The figure has aspect = width/height (px).
    if aspect >= 1.0:
        w_mm = figure_scale_mm
        h_mm = figure_scale_mm / aspect
    else:
        h_mm = figure_scale_mm
        w_mm = figure_scale_mm * aspect
    out: list[tuple[float, float]] = []
    for x, y in pts:
        wx = (float(x) - 0.5) * w_mm
        # Flip Y: image y grows downward, world Y grows upward.
        wy = (0.5 - float(y)) * h_mm
        out.append((wx, wy))
    return out


def _dedupe_consecutive(pts: list[tuple[float, float]], min_d: float = 0.01) -> list[tuple[float, float]]:
    if not pts:
        return pts
    out = [pts[0]]
    for p in pts[1:]:
        dx = p[0] - out[-1][0]
        dy = p[1] - out[-1][1]
        if (dx * dx + dy * dy) >= min_d * min_d:
            out.append(p)
    # Also drop the closing duplicate if present.
    if len(out) > 1:
        dx = out[0][0] - out[-1][0]
        dy = out[0][1] - out[-1][1]
        if (dx * dx + dy * dy) < min_d * min_d:
            out.pop()
    return out


def build_extrusion(
    outline: ComponentOutline,
    *,
    figure_scale_mm: float,
    aspect: float,
    component_label: str | None = None,
) -> ExtrusionResult:
    """Build a single extruded solid from an outline. Returns None solid
    on validation failure with diagnostics populated."""
    diag: list[str] = []
    if not outline.polygon_norm or len(outline.polygon_norm) < 3:
        return ExtrusionResult(
            component_id=outline.component_id,
            solid=None,
            notes=f"polygon has {len(outline.polygon_norm)} points",
            diagnostics=["empty/short polygon"],
        )
    world = _norm_to_world_xy(
        outline.polygon_norm,
        figure_scale_mm=figure_scale_mm,
        aspect=aspect,
    )
    world = _dedupe_consecutive(world)
    if len(world) < 3:
        return ExtrusionResult(
            component_id=outline.component_id,
            solid=None,
            notes="polygon collapsed after dedupe",
            diagnostics=[f"{len(world)} unique points"],
        )

    depth = max(0.5, float(outline.extrude_depth_mm))
    z_off = float(outline.z_offset_mm)

    # Hole polygons in world coords.
    hole_worlds: list[list[tuple[float, float]]] = []
    for h in outline.holes_norm or []:
        hw = _norm_to_world_xy(h, figure_scale_mm=figure_scale_mm, aspect=aspect)
        hw = _dedupe_consecutive(hw)
        if len(hw) >= 3:
            hole_worlds.append(hw)

    try:
        with bd.BuildPart() as part:
            with bd.BuildSketch() as sk:
                bd.Polygon(*world, align=None)
                for hw in hole_worlds:
                    bd.Polygon(*hw, align=None, mode=bd.Mode.SUBTRACT)
            bd.extrude(amount=depth)
        # Recentre Z so the slab is around z = z_off + depth/2.
        # build123d's extrude adds in +Z; we shift to put the part's base
        # at z_off so a "z_offset 0" sheet sits at the world XY plane.
        solid = part.part.translate((0, 0, z_off))
        if component_label:
            solid.label = component_label
    except Exception as exc:  # noqa: BLE001
        return ExtrusionResult(
            component_id=outline.component_id,
            solid=None,
            notes=f"build123d failed: {exc}",
            diagnostics=[type(exc).__name__],
        )

    bb = solid.bounding_box()
    size = (bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
    if min(size) < 0.1:
        return ExtrusionResult(
            component_id=outline.component_id,
            solid=None,
            bbox_mm=size,
            notes=f"degenerate bbox {size}",
            diagnostics=["min dimension < 0.1mm"],
        )
    diag.append(f"poly={len(world)}pts, holes={len(hole_worlds)}, depth={depth}mm")
    return ExtrusionResult(
        component_id=outline.component_id,
        solid=solid,
        bbox_mm=size,
        notes="ok",
        diagnostics=diag,
    )


def build_assembly_from_outlines(
    outline_set: OutlineSet,
    *,
    component_labels: dict[str, str] | None = None,
) -> tuple[bd.Compound, list[str], list[ExtrusionResult]]:
    """Build a flat compound with one extruded solid per outline.

    Returns (compound, ordered_ids, per-component results). The compound
    is **flat** (no nested compounds), so each component_id ends up as a
    direct top-level child — which means the v1.0 GLB-naming postprocess
    (rename_glb_root_children) preserves every component_id as a GLB
    node name. That's the contract the viewer relies on for span↔mesh
    highlights.
    """
    aspect = outline_set.figure_width_px / max(1, outline_set.figure_height_px)
    children: list[bd.Part | bd.Compound] = []
    ordered: list[str] = []
    results: list[ExtrusionResult] = []
    for o in outline_set.outlines:
        label = (component_labels or {}).get(o.component_id, o.component_id)
        result = build_extrusion(
            o,
            figure_scale_mm=outline_set.figure_scale_mm,
            aspect=aspect,
            component_label=o.component_id,
        )
        results.append(result)
        if result.solid is not None:
            children.append(result.solid)
            ordered.append(o.component_id)
        else:
            logger.warning(
                "skipping %s: %s (%s)",
                o.component_id,
                result.notes,
                "; ".join(result.diagnostics),
            )
    if not children:
        raise RuntimeError("No buildable extrusions in outline set")
    compound = bd.Compound(label="assembly", children=children)
    return compound, ordered, results


__all__ = [
    "ExtrusionResult",
    "build_extrusion",
    "build_assembly_from_outlines",
]
