"""V13-L — PlanetaryGearScaffold.

Distinct from `rotary_shaft` (which stacks parts coaxially): a
planetary gear's defining geometry is that the planet pinions
**orbit** the sun gear at a shared radius around the central
axis. This scaffold lays:

  * housing  — large hollow cylinder centered on Z,
  * ring gear(s) — annular rings inside the housing,
  * sun gear — short cylinder at the origin,
  * N planet pinions — distributed at angles 2π·k/N around the
    sun, at orbital radius r_orbit,
  * carrier — disc connecting the planet centers,
  * input + output shafts — protruding along ±Z from the
    housing ends,
  * mounting bosses — flanking the housing.

Used by US3705522A_planetary_gear_with_idler (3 planet pinions
+ idler + first/second ring gears).
"""
from __future__ import annotations

import logging
import math

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold,
    ScaffoldInput,
    ScaffoldResult,
    register_scaffold,
)

logger = logging.getLogger(__name__)


_HOUSING_R = 50.0
_HOUSING_INNER_R = 42.0
_HOUSING_H = 64.0
_RING_R = 38.0
_RING_INNER_R = 30.0
_RING_H = 18.0
_SUN_R = 12.0
_SUN_H = 16.0
_PLANET_R = 9.0
_PLANET_H = 16.0
_ORBIT_R = 22.0
_CARRIER_R = 26.0
_CARRIER_INNER_R = 20.0
_CARRIER_H = 4.0
_SHAFT_R = 5.0


def _ring(outer_r: float, inner_r: float, h: float) -> bd.Part:
    o = bd.Cylinder(radius=outer_r, height=h)
    i = bd.Cylinder(radius=inner_r, height=h + 2.0)
    return o - i


_PLANET_KEYWORDS = ("planet pinion", "planet gear", "planet wheel",
                     "idler pinion", "idler gear")


_ROUTING_SINGLE: list[tuple[str, tuple[str, ...]]] = [
    ("housing", ("housing", "stationary housing",
                  "case", "case cover", "casing")),
    ("sun_gear", ("sun gear", "central gear",
                   "central pinion")),
    ("input_shaft", ("input shaft", "input")),
    ("output_shaft", ("output shaft", "output")),
    ("carrier", ("carrier", "planet carrier",
                  "spider", "cage")),
    ("mount_first", ("first mounting", "first mount",
                      "first bearing", "first boss")),
    ("mount_second", ("second mounting", "second mount",
                       "second bearing", "second boss")),
]


@register_scaffold
class PlanetaryGearScaffold(Scaffold):
    """Planetary gear with explicit orbital layout for planet
    pinions. Counts ring gears and planet pinions in the claim
    map, then places ring gears stacked along Z and planets
    around the orbit at evenly-spaced angles."""

    scaffold_id = "planetary_gear"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)

        # Count how many planet pinions and ring gears we expect.
        planet_cids: list[str] = []
        ring_cids: list[str] = []
        other_cids: list[str] = []
        for cid in cids:
            low = inputs.component_label(cid).lower()
            if any(k in low for k in _PLANET_KEYWORDS):
                planet_cids.append(cid)
            elif "ring gear" in low or "annulus" in low:
                ring_cids.append(cid)
            else:
                other_cids.append(cid)

        n_planets = max(len(planet_cids), 3)
        # Pre-compute planet positions on the orbit.
        planet_positions: list[tuple[float, float]] = []
        for i in range(n_planets):
            angle = 2.0 * math.pi * i / n_planets
            planet_positions.append((
                _ORBIT_R * math.cos(angle),
                _ORBIT_R * math.sin(angle),
            ))

        # ---- Build canonical structural meshes ----
        housing = _ring(_HOUSING_R, _HOUSING_INNER_R, _HOUSING_H)
        sun_gear = bd.Cylinder(radius=_SUN_R, height=_SUN_H)
        carrier = _ring(_CARRIER_R, _CARRIER_INNER_R, _CARRIER_H)
        carrier = carrier.translate((0.0, 0.0, +_HOUSING_H * 0.5 - _CARRIER_H * 0.5 - 2.0))
        # Ring gears stacked along Z (sectional view of US3705522A
        # has two ring gears side-by-side).
        ring_meshes: list[bd.Part] = []
        ring_zs = [-_RING_H * 0.6, +_RING_H * 0.6]
        for i in range(max(2, len(ring_cids))):
            z = ring_zs[i % 2] if len(ring_cids) <= 2 else (
                -_RING_H * 0.8 + i * (_RING_H * 1.2))
            r = _ring(_RING_R, _RING_INNER_R, _RING_H).translate(
                (0.0, 0.0, z))
            ring_meshes.append(r)

        # Shafts extend along ±Z from the housing ends.
        input_shaft = bd.Cylinder(
            radius=_SHAFT_R, height=80.0).translate(
            (0.0, 0.0, -_HOUSING_H * 0.5 - 30.0))
        output_shaft = bd.Cylinder(
            radius=_SHAFT_R, height=80.0).translate(
            (0.0, 0.0, +_HOUSING_H * 0.5 + 30.0))

        # Mounting bosses — small cylinders flanking the housing
        # rim.
        mount_first = bd.Cylinder(radius=4.0, height=10.0).translate(
            (+_HOUSING_R + 6.0, +6.0, 0.0))
        mount_second = bd.Cylinder(radius=4.0, height=10.0).translate(
            (-_HOUSING_R - 6.0, -6.0, 0.0))

        single_meshes: dict[str, bd.Part] = {
            "housing": housing,
            "sun_gear": sun_gear,
            "carrier": carrier,
            "input_shaft": input_shaft,
            "output_shaft": output_shaft,
            "mount_first": mount_first,
            "mount_second": mount_second,
        }

        # ---- Route claim ids ----
        children: list[bd.Part] = []
        ordered: list[str] = []
        used_single: set[str] = set()
        used_planet_idx = 0
        used_ring_idx = 0

        for cid in cids:
            low = inputs.component_label(cid).lower()
            placed = False

            # Planet pinion?
            if any(k in low for k in _PLANET_KEYWORDS):
                idx = used_planet_idx
                used_planet_idx += 1
                if idx < len(planet_positions):
                    cx, cy = planet_positions[idx]
                else:
                    # Extra idlers — place slightly inside orbit.
                    angle = 2.0 * math.pi * idx / max(n_planets, 1)
                    cx = (_ORBIT_R - 6.0) * math.cos(angle)
                    cy = (_ORBIT_R - 6.0) * math.sin(angle)
                pinion = bd.Cylinder(radius=_PLANET_R, height=_PLANET_H)
                pinion = pinion.translate((cx, cy, 0.0))
                pinion.label = cid
                children.append(pinion)
                ordered.append(cid)
                placed = True

            # Ring gear?
            elif "ring gear" in low or "annulus" in low:
                idx = used_ring_idx
                used_ring_idx += 1
                if idx < len(ring_meshes):
                    rg = ring_meshes[idx]
                else:
                    z = -_RING_H * 0.8 + idx * (_RING_H * 1.2)
                    rg = _ring(_RING_R, _RING_INNER_R,
                                _RING_H).translate((0.0, 0.0, z))
                rg.label = cid
                children.append(rg)
                ordered.append(cid)
                placed = True

            # Single named structural mesh?
            else:
                target = self._route_single(low)
                mesh = single_meshes.get(target) if target else None
                if mesh is not None and target not in used_single:
                    mesh.label = cid
                    children.append(mesh)
                    ordered.append(cid)
                    used_single.add(target)
                    placed = True
                elif mesh is not None:
                    bb = mesh.bounding_box()
                    m = bd.Sphere(radius=1.6).translate(
                        (bb.max.X + 4.0,
                         (bb.min.Y + bb.max.Y) * 0.5,
                         bb.max.Z + 4.0))
                    m.label = cid
                    children.append(m)
                    ordered.append(cid)
                    placed = True

            if not placed:
                # Marker on the housing rim, biased radially out so
                # not coincident with anything else.
                idx = sum(1 for x in ordered) % 8
                a = idx * (math.pi / 4.0) + 0.2
                m = bd.Sphere(radius=1.6).translate(
                    ((_HOUSING_R + 8.0) * math.cos(a),
                     (_HOUSING_R + 8.0) * math.sin(a),
                     0.0))
                m.label = cid
                children.append(m)
                ordered.append(cid)

        # Emit structural meshes that nobody claimed (so the
        # housing / sun / carrier are always visible).
        for name in ("housing", "sun_gear", "carrier",
                      "input_shaft", "output_shaft"):
            if name in used_single:
                continue
            mesh = single_meshes[name]
            mesh.label = name
            children.append(mesh)
            ordered.append(name)
        # Emit ring gears that weren't claimed.
        for i in range(used_ring_idx, len(ring_meshes)):
            rg = ring_meshes[i]
            rg.label = f"ring_gear_{i + 1}"
            children.append(rg)
            ordered.append(f"ring_gear_{i + 1}")
        # Emit planet pinions that weren't claimed (round out to
        # at least 3 so the orbital geometry reads).
        for i in range(used_planet_idx, n_planets):
            cx, cy = planet_positions[i]
            pinion = bd.Cylinder(radius=_PLANET_R, height=_PLANET_H)
            pinion = pinion.translate((cx, cy, 0.0))
            pinion.label = f"planet_pinion_{i + 1}"
            children.append(pinion)
            ordered.append(f"planet_pinion_{i + 1}")

        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound,
            ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={
                "n_components": n,
                "n_planets": max(len(planet_cids), n_planets),
                "n_ring_gears": max(len(ring_cids), len(ring_meshes)),
                "orbit_radius": _ORBIT_R,
            },
            quality_tier="good",
        )

    @staticmethod
    def _route_single(label: str) -> str | None:
        for target, kws in _ROUTING_SINGLE:
            if any(k in label for k in kws):
                return target
        return None
