"""V13-B + V14-E — RotaryShaftScaffold.

For harmonic drives, transmissions, rotors, shaft assemblies.
V14-E: replaced ad-hoc primitives with v14_primitives helpers
so geometry reads as gears / bearings instead of nested
cylinders.

Note: planetary gears now have their own
PlanetaryGearScaffold (V13-L) — RotaryShaftScaffold is the
fallback for non-planetary rotary mechanisms.
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
from claim2cad import v14_primitives as v14p

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


@register_scaffold
class RotaryShaftScaffold(Scaffold):
    """Coaxial layout: shafts, gears, bearings stacked on Z."""

    scaffold_id = "rotary_shaft"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # Geometry library — V14-E uses richer primitives
        # (toothed gears, ball bearings, flanged housings).
        def geom_for(label: str) -> tuple[bd.Part, str]:
            low = label.lower()
            if any(k in low for k in ("ring gear", "annulus")):
                return (v14p.ring_gear(outer_r=36.0, inner_r=28.0,
                                          height=14.0,
                                          n_teeth=24),
                        "ring_gear")
            if any(k in low for k in ("planet gear", "planet wheel")):
                return v14p.planet_gear(radius=10.0,
                                          height=12.0), "planet_gear"
            if any(k in low for k in ("sun gear", "central gear")):
                return v14p.sun_gear(radius=14.0,
                                       height=12.0), "sun_gear"
            if any(k in low for k in ("carrier", "spider", "cage")):
                return (v14p.ring_gear(outer_r=28.0, inner_r=20.0,
                                          height=6.0,
                                          n_teeth=8),
                        "carrier")
            if "input" in low:
                return v14p.keyed_shaft(radius=5.0,
                                          length=70.0), "input_shaft"
            if "output" in low:
                return v14p.keyed_shaft(radius=5.0,
                                          length=70.0), "output_shaft"
            if "shaft" in low or "axle" in low:
                return v14p.splined_shaft(radius=4.0,
                                            length=80.0), "shaft"
            if any(k in low for k in ("bearing", "bushing")):
                return v14p.ball_bearing(outer_r=8.0,
                                            inner_r=5.0,
                                            height=4.0,
                                            n_balls=8), "bearing"
            if any(k in low for k in ("housing", "case",
                                       "enclosure")):
                return (v14p.flanged_housing(body_radius=45.0,
                                                body_height=60.0,
                                                flange_radius=55.0,
                                                flange_height=8.0,
                                                n_holes=6),
                        "housing")
            if any(k in low for k in ("hole", "passage")):
                return bd.Sphere(radius=2.0), "hole_marker"
            if any(k in low for k in ("flexspline", "flex spline",
                                       "flexible")):
                return (v14p.ring_gear(outer_r=24.0, inner_r=20.0,
                                          height=24.0,
                                          n_teeth=30),
                        "flexspline")
            if "wave generator" in low:
                return v14p.eccentric_cam(radius=14.0,
                                            height=10.0,
                                            eccentricity=4.0), "wave_generator"
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
            # V14-E: now using toothed gears + ball bearings +
            # flanged housings → good.
            quality_tier="good",
        )
