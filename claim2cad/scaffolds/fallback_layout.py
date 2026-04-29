"""V13-B — FallbackGridScaffold.

For examples we don't have a specific template for. Critical
property: never a central pile. Components are placed in a
spatial grid, optionally pulled toward their figure_uv anchor
when figure data exists.

This is the safety net for V13. Every example that doesn't match
a specific scaffold (door_hinge, rotary_shaft, linkage,
bracket_mount, housing_panel) falls through to here.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


# Per-component-name shape hint — drive primitive choice from the
# component label so a "shaft" is a cylinder, a "panel" is a thin
# plate, etc. Stays deterministic; no LLM.
_LABEL_SHAPE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("shaft", "rotor", "spindle", "axle", "pin"), "shaft"),
    (("gear", "wheel", "ring", "pulley", "sprocket"), "disc"),
    (("panel", "plate", "wall", "cover", "frame", "leaf"), "plate"),
    (("housing", "case", "enclosure", "body"), "block"),
    (("link", "arm", "lever", "extension"), "link"),
    (("bracket", "mount", "flange", "support"), "bracket"),
    (("hole", "opening", "passage", "bore"), "hole"),
    (("bearing", "bushing", "boss", "collar"), "ring"),
    (("fastener", "bolt", "screw", "nut"), "fastener"),
]


def _shape_hint(label: str) -> str:
    low = label.lower()
    for keys, hint in _LABEL_SHAPE_HINTS:
        if any(k in low for k in keys):
            return hint
    return "block"


def _build_primitive(hint: str) -> bd.Part:
    """Tiny shape library for the fallback. Each primitive is sized
    to ~30-50 mm so a grid layout reads well."""
    if hint == "shaft":
        return bd.Cylinder(radius=4.0, height=80.0)
    if hint == "disc":
        return bd.Cylinder(radius=18.0, height=8.0)
    if hint == "plate":
        return bd.Box(60.0, 4.0, 40.0)
    if hint == "block":
        return bd.Box(40.0, 30.0, 30.0)
    if hint == "link":
        return bd.Box(50.0, 6.0, 14.0)
    if hint == "bracket":
        # L-shape: vertical + horizontal plates
        v = bd.Box(8.0, 30.0, 30.0)
        h = bd.Box(30.0, 30.0, 8.0).translate((11.0, 0.0, -11.0))
        return v + h
    if hint == "ring":
        outer = bd.Cylinder(radius=10.0, height=6.0)
        inner = bd.Cylinder(radius=6.0, height=8.0)
        return outer - inner
    if hint == "fastener":
        head = bd.Cylinder(radius=2.5, height=2.0).translate((0, 0, 5.0))
        shaft = bd.Cylinder(radius=1.2, height=10.0)
        return head + shaft
    if hint == "hole":
        # Holes are tiny markers; not real solids.
        return bd.Sphere(radius=2.0)
    return bd.Box(20.0, 20.0, 20.0)


@register_scaffold
class FallbackGridScaffold(Scaffold):
    """Coherent grid layout for any example. Pulls components
    toward their figure_uv anchor when figure_map is present;
    otherwise lays them out on a uniform 3-D grid biased by the
    component's shape hint (panels at the back, shafts and rings
    in the middle, fasteners at the periphery).
    """

    scaffold_id = "fallback_grid"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids()
        if not cids:
            cids = ["component_0"]

        # Resolve per-component figure_uv if available.
        callout_uv: dict[str, tuple[float, float]] = {}
        if inputs.figure_map:
            comp_to_num = inputs.figure_map.get("component_to_number") or {}
            labels = inputs.figure_map.get("vlm_labels") or []
            num_to_uv: dict[str, tuple[float, float]] = {}
            for lab in labels:
                num = str(lab.get("number") or "").strip()
                pos = lab.get("approximate_position") or []
                if num and len(pos) >= 2:
                    try:
                        num_to_uv[num] = (float(pos[0]), float(pos[1]))
                    except (TypeError, ValueError):
                        continue
            for cid, num in comp_to_num.items():
                if str(num) in num_to_uv:
                    callout_uv[cid] = num_to_uv[str(num)]

        # Layout strategy:
        #   For each component, derive a (X, Z) target. Use figure_uv
        #   if available; otherwise fall back to a row-major grid.
        #   Y is determined by shape hint (back = panels, front =
        #   small parts).
        children: list[bd.Part] = []
        ordered: list[str] = []
        n = len(cids)
        cols = max(2, int(math.ceil(math.sqrt(n * 1.4))))
        spacing_x = 70.0
        spacing_z = 70.0

        layer_y_map = {
            "plate": -45.0,
            "block": -10.0,
            "bracket": +5.0,
            "link": +5.0,
            "shaft": 0.0,
            "disc": 0.0,
            "ring": 0.0,
            "fastener": +20.0,
            "hole": +28.0,
        }

        for i, cid in enumerate(cids):
            label = inputs.component_label(cid)
            hint = _shape_hint(label)
            try:
                solid = _build_primitive(hint)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Primitive %s failed for %s: %s", hint, cid, exc)
                solid = bd.Box(20.0, 20.0, 20.0)

            # Target position
            if cid in callout_uv:
                u, v = callout_uv[cid]
                # Map [0..1] → world span 240 mm centred at 0.
                cx = (u - 0.5) * 240.0
                cz = (0.5 - v) * 240.0
            else:
                row = i // cols
                col = i % cols
                cx = (col - (cols - 1) / 2.0) * spacing_x
                cz = -row * spacing_z + (n // cols) * spacing_z / 2
            cy = layer_y_map.get(hint, 0.0)

            solid = solid.translate((cx, cy, cz))
            solid.label = cid
            children.append(solid)
            ordered.append(cid)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={
                "n_components": n,
                "n_with_figure_uv": len(callout_uv),
                "cols": cols,
            },
            quality_tier="fallback",
        )
