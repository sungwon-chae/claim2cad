"""V13-B — RotaryShaftScaffold.

For planetary gears, harmonic drives, transmissions, rotors,
shaft assemblies. Lays parts out along a horizontal Z-axis with
discs / gears stacked coaxially, supports/bearings flanking.
"""
from __future__ import annotations

import logging

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


_ROTARY_KEYWORDS = [
    ("ring_gear", ("ring gear", "annulus")),
    ("sun_gear", ("sun gear", "central gear")),
    ("planet_gear", ("planet gear", "planet wheel")),
    ("carrier", ("carrier", "spider", "cage")),
    ("input_shaft", ("input", "drive shaft")),
    ("output_shaft", ("output", "driven shaft")),
    ("bearing", ("bearing", "bushing", "boss")),
    ("housing", ("housing", "case", "cover")),
    ("flexspline", ("flexspline", "flex spline", "flexible")),
    ("wave_generator", ("wave generator",)),
]


def _ring(outer_r: float, inner_r: float, height: float) -> bd.Part:
    o = bd.Cylinder(radius=outer_r, height=height)
    i = bd.Cylinder(radius=inner_r, height=height + 2.0)
    return o - i


@register_scaffold
class RotaryShaftScaffold(Scaffold):
    """Coaxial layout: shafts, gears, bearings stacked on Z."""

    scaffold_id = "rotary_shaft"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # Geometry library (small, deterministic).
        def geom_for(label: str) -> tuple[bd.Part, str]:
            low = label.lower()
            if any(k in low for k in ("ring gear", "annulus")):
                return _ring(36.0, 28.0, 14.0), "ring_gear"
            if any(k in low for k in ("planet gear", "planet wheel")):
                return bd.Cylinder(radius=10.0, height=12.0), "planet_gear"
            if any(k in low for k in ("sun gear", "central gear")):
                return bd.Cylinder(radius=14.0, height=12.0), "sun_gear"
            if any(k in low for k in ("carrier", "spider", "cage")):
                return _ring(28.0, 20.0, 6.0), "carrier"
            if "input" in low:
                return bd.Cylinder(radius=5.0, height=70.0), "input_shaft"
            if "output" in low:
                return bd.Cylinder(radius=5.0, height=70.0), "output_shaft"
            if "shaft" in low or "axle" in low:
                return bd.Cylinder(radius=4.0, height=80.0), "shaft"
            if any(k in low for k in ("bearing", "bushing")):
                return _ring(8.0, 5.0, 4.0), "bearing"
            if any(k in low for k in ("housing", "case", "enclosure")):
                return _ring(45.0, 38.0, 90.0), "housing"
            if any(k in low for k in ("hole", "passage")):
                return bd.Sphere(radius=2.0), "hole_marker"
            return bd.Cylinder(radius=8.0, height=10.0), "generic"

        # Layout — group by kind, stack along +Z within each group.
        kind_z_offset = {
            "housing": -10.0,         # housing wraps the whole assembly (centred)
            "input_shaft": -55.0,     # at the negative end
            "carrier": -30.0,
            "sun_gear": -15.0,
            "ring_gear": -10.0,
            "planet_gear": -10.0,
            "output_shaft": +55.0,
            "shaft": 0.0,
            "bearing": +30.0,
            "hole_marker": +45.0,
            "generic": +20.0,
        }
        # Within a kind, spread radially around Z axis to avoid
        # coincident bboxes (which break STEP export — see V12-C).
        kind_angle: dict[str, float] = {}
        kind_count: dict[str, int] = {}

        children: list[bd.Part] = []
        ordered: list[str] = []
        for cid in cids:
            label = inputs.component_label(cid)
            mesh, kind = geom_for(label)
            kind_count[kind] = kind_count.get(kind, 0) + 1
            cnt = kind_count[kind]
            # Angle around Z for radial spread.
            angle = (cnt - 1) * 60.0
            r = 0.0 if cnt == 1 else 22.0
            import math
            cx = r * math.cos(math.radians(angle))
            cy = r * math.sin(math.radians(angle))
            cz = kind_z_offset.get(kind, 0.0)
            mesh = mesh.translate((cx, cy, cz))
            mesh.label = cid
            children.append(mesh)
            ordered.append(cid)

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": n,
                          "kind_distribution": kind_count},
            quality_tier="partial",
        )
