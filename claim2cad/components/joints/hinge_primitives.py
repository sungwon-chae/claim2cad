"""True 3D hinge primitives for the V11-14 assembly solver (V11-18).

The V11-14 solver picked simple primitives (``Box`` for plate/bracket,
``Cylinder`` for pin) that produced topologically-correct geometry but
had no fillets, no integrated barrels, no drilled bores. The audit on
US4807331A_spring_loaded_hinge showed 21/25 components had **zero**
cylindrical / curved faces — the assembly looked like a stack of
flat slabs, not a hinge.

This module provides true mechanical 3D primitives for the parts that
make a hinge actually look like a hinge:

* :class:`HingeKnuckle` — a hollow barrel with optional shoulder rings.
* :class:`HingeLeafWithKnuckles` — a plate with one or more knuckle
  barrels along its hinge edge, alternating top/bottom for nesting.
* :class:`HingeShaft` — a pin / pintle / shaft with optional chamfered
  ends, snap-ring groove, and round/flat head.
* :class:`HingeBracketC` — a C-shaped main-member bracket with
  upper/lower extension barrels integrated into the body so the
  pin passes through cylindrical holes, not extruded slots.
* :class:`Washer`, :class:`Boss` — small annular helpers for stacked
  hinge parts.

All five are pure ``build123d`` parts. Their result is a ``Part``
with at least one curved face (cylinder, sphere, or torus); the
audit threshold ``n_cyl > 0`` flips from 0 → ≥1 just by switching to
these.

Each primitive's parameters route VLM-natural names through aliases
(see :mod:`claim2cad.components.library`) so a shape_inference call
that emits ``{"diameter_mm": 8, "depth_mm": 12}`` still hits the
canonical ``barrel_outer_diameter`` / ``barrel_height`` fields.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import (
    Component,
    ComponentBuildError,
    _require_positive,
)
from claim2cad.components.library import register


# ---------------------------------------------------------------------------
# HingeKnuckle
# ---------------------------------------------------------------------------


@dataclass
class HingeKnuckle(Component):
    """Hollow cylindrical hinge knuckle (a.k.a. barrel) along Z.

    Parameters
    ----------
    barrel_outer_diameter : float, mm
    barrel_inner_diameter : float, mm — through-bore for the pin
    barrel_height : float, mm — extent along Z
    chamfer_mm : float, mm — top+bottom edge chamfer (0 = sharp)
    shoulder_diameter : float, mm — outer diameter of optional end
        shoulder rings (0 disables)
    shoulder_height : float, mm — depth of shoulder rings (each end)
    """

    barrel_outer_diameter: float = 14.0
    barrel_inner_diameter: float = 6.0
    barrel_height: float = 18.0
    chamfer_mm: float = 0.6
    shoulder_diameter: float = 0.0
    shoulder_height: float = 0.0

    def validate(self) -> None:
        _require_positive("barrel_outer_diameter", self.barrel_outer_diameter)
        _require_positive("barrel_inner_diameter", self.barrel_inner_diameter)
        _require_positive("barrel_height", self.barrel_height)
        if self.barrel_inner_diameter >= self.barrel_outer_diameter:
            raise ComponentBuildError(
                "barrel_inner_diameter must be < barrel_outer_diameter"
            )
        if self.chamfer_mm < 0 or self.chamfer_mm * 2 >= self.barrel_height:
            raise ComponentBuildError(
                "chamfer_mm must be >= 0 and < barrel_height/2"
            )
        if self.shoulder_diameter < 0:
            raise ComponentBuildError("shoulder_diameter must be >= 0")
        if self.shoulder_diameter and self.shoulder_diameter <= self.barrel_outer_diameter:
            raise ComponentBuildError(
                "shoulder_diameter must be > barrel_outer_diameter when present"
            )

    def _build_solid(self) -> bd.Part:
        ro = self.barrel_outer_diameter / 2.0
        ri = self.barrel_inner_diameter / 2.0
        h = self.barrel_height
        with bd.BuildPart() as p:
            bd.Cylinder(ro, h)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(ri, h * 1.05, mode=bd.Mode.SUBTRACT)
            if self.chamfer_mm > 0:
                # Chamfer the outer top + bottom edges — gives the barrel
                # the visible bevel real hinge knuckles always have.
                try:
                    edges = (
                        p.part.edges()
                        .filter_by(bd.GeomType.CIRCLE)
                        .group_by(bd.Axis.Z)
                    )
                    if edges and len(edges[0]) > 0 and len(edges[-1]) > 0:
                        bd.chamfer(
                            list(edges[0]) + list(edges[-1]),
                            length=self.chamfer_mm,
                        )
                except Exception:  # noqa: BLE001 — chamfer is decorative
                    pass
            if self.shoulder_diameter > 0 and self.shoulder_height > 0:
                sd = self.shoulder_diameter
                sh = self.shoulder_height
                # Top shoulder.
                with bd.Locations((0, 0, h / 2.0 + sh / 2.0)):
                    bd.Cylinder(sd / 2.0, sh)
                # Bottom shoulder.
                with bd.Locations((0, 0, -(h / 2.0 + sh / 2.0))):
                    bd.Cylinder(sd / 2.0, sh)
                # Re-drill the bore through the shoulders.
                with bd.Locations((0, 0, 0)):
                    bd.Cylinder(ri, h * 1.5 + sh * 2, mode=bd.Mode.SUBTRACT)
        return p.part


_KNUCKLE_PARAM_ALIASES = {
    "od": "barrel_outer_diameter",
    "outer_diameter": "barrel_outer_diameter",
    "diameter": "barrel_outer_diameter",
    "id": "barrel_inner_diameter",
    "bore": "barrel_inner_diameter",
    "inner_diameter": "barrel_inner_diameter",
    "height": "barrel_height",
    "length": "barrel_height",
    "depth": "barrel_height",
    "depth_mm": "barrel_height",
    "thickness": "barrel_height",
}

_KNUCKLE_PARAM_SCHEMA = {
    "barrel_outer_diameter": "float, mm",
    "barrel_inner_diameter": "float, mm — through-bore",
    "barrel_height": "float, mm — Z extent",
    "chamfer_mm": "float, mm — outer-edge bevel",
}


@register(
    "hinge_knuckle",
    aliases=("knuckle", "hinge_barrel", "barrel"),
    description="Hollow cylindrical hinge knuckle / barrel.",
    param_aliases=_KNUCKLE_PARAM_ALIASES,
    param_schema=_KNUCKLE_PARAM_SCHEMA,
)
def make_hinge_knuckle(**kwargs) -> HingeKnuckle:
    return HingeKnuckle(**kwargs)


# ---------------------------------------------------------------------------
# HingeLeafWithKnuckles
# ---------------------------------------------------------------------------


@dataclass
class HingeLeafWithKnuckles(Component):
    """Hinge leaf — a plate with N knuckle barrels along its hinge edge.

    The barrel(s) are integrated into the leaf body so the resulting
    solid has a real cylindrical face along the hinge axis (not just an
    extrusion).

    Parameters
    ----------
    leaf_width : float, mm — extent in X (away from the hinge axis)
    leaf_height : float, mm — extent in Z (along the hinge axis)
    leaf_thickness : float, mm — sheet thickness in Y
    barrel_outer_diameter : float, mm
    barrel_inner_diameter : float, mm
    knuckle_count : int — number of barrels stacked along the hinge edge
    knuckle_pattern_offset : int (0 or 1) — phase: 0 means "this leaf
        carries the even-indexed barrels" (top, then skip, ...),
        1 means odd-indexed (skip, then barrel, ...). Used to
        nest two leaves so their barrels interleave.
    fillet_corners_mm : float, mm — leaf-corner fillet on the side
        opposite the hinge axis
    """

    leaf_width: float = 60.0
    leaf_height: float = 80.0
    leaf_thickness: float = 4.0
    barrel_outer_diameter: float = 14.0
    barrel_inner_diameter: float = 6.0
    knuckle_count: int = 3
    knuckle_pattern_offset: int = 0
    fillet_corners_mm: float = 2.0

    def validate(self) -> None:
        for n in (
            "leaf_width",
            "leaf_height",
            "leaf_thickness",
            "barrel_outer_diameter",
            "barrel_inner_diameter",
        ):
            _require_positive(n, getattr(self, n))
        if self.barrel_inner_diameter >= self.barrel_outer_diameter:
            raise ComponentBuildError("inner_diameter must be < outer_diameter")
        if self.knuckle_count < 1:
            raise ComponentBuildError("knuckle_count must be >= 1")
        if self.knuckle_pattern_offset not in (0, 1):
            raise ComponentBuildError("knuckle_pattern_offset must be 0 or 1")

    def _build_solid(self) -> bd.Part:
        bw = self.leaf_width
        bh = self.leaf_height
        bt = self.leaf_thickness
        ro = self.barrel_outer_diameter / 2.0
        ri = self.barrel_inner_diameter / 2.0

        # Leaf body: rectangular sheet centred on origin, with hinge
        # edge along -X (so the barrels are at x = -bw/2).
        with bd.BuildPart() as p:
            bd.Box(bw, bt, bh)
            # Round the corners on the +X side (away from the hinge).
            if self.fillet_corners_mm > 0:
                try:
                    fx = bw / 2.0
                    edges_to_fillet = []
                    for e in p.part.edges():
                        c = e.center()
                        if abs(c.X - fx) < 1.5 and abs(e.length - bt) < 0.1:
                            edges_to_fillet.append(e)
                    if edges_to_fillet:
                        bd.fillet(edges_to_fillet, self.fillet_corners_mm)
                except Exception:  # noqa: BLE001
                    pass
            # Knuckle barrels — phase ``knuckle_pattern_offset`` skips
            # alternate slots so a paired leaf can nest into the gaps.
            seg_h = bh / max(self.knuckle_count, 1)
            for i in range(self.knuckle_count):
                if (i % 2) != self.knuckle_pattern_offset:
                    continue
                z_centre = -bh / 2.0 + (i + 0.5) * seg_h
                with bd.Locations((-bw / 2.0, 0, z_centre)):
                    # Build the barrel along Z.
                    bd.Cylinder(ro, seg_h)
            # Drill the through-bore down the entire hinge axis (-bw/2, 0, *).
            with bd.Locations((-bw / 2.0, 0, 0)):
                bd.Cylinder(ri, bh * 1.05, mode=bd.Mode.SUBTRACT)
        return p.part


_LEAF_KNUCKLE_PARAM_ALIASES = {
    "width": "leaf_width",
    "height": "leaf_height",
    "thickness": "leaf_thickness",
    "depth": "leaf_thickness",
    "od": "barrel_outer_diameter",
    "outer_diameter": "barrel_outer_diameter",
    "id": "barrel_inner_diameter",
    "bore": "barrel_inner_diameter",
    "n_knuckles": "knuckle_count",
    "barrels": "knuckle_count",
}


@register(
    "hinge_leaf_with_knuckles",
    aliases=("hinge_leaf_3d", "leaf_knuckle_assembly"),
    description="Hinge leaf with integrated knuckle barrels along the hinge edge.",
    param_aliases=_LEAF_KNUCKLE_PARAM_ALIASES,
    param_schema={
        "leaf_width": "float, mm — extent away from the hinge axis (X)",
        "leaf_height": "float, mm — extent along the hinge axis (Z)",
        "leaf_thickness": "float, mm — sheet thickness (Y)",
        "barrel_outer_diameter": "float, mm",
        "barrel_inner_diameter": "float, mm",
        "knuckle_count": "int >= 1",
        "knuckle_pattern_offset": "int (0 or 1) — alternates with paired leaf",
    },
)
def make_hinge_leaf_with_knuckles(**kwargs) -> HingeLeafWithKnuckles:
    return HingeLeafWithKnuckles(**kwargs)


# ---------------------------------------------------------------------------
# HingeShaft
# ---------------------------------------------------------------------------


@dataclass
class HingeShaft(Component):
    """Cylindrical hinge pin / pintle / shaft along Z, with optional
    end features.

    Parameters
    ----------
    diameter : float, mm
    length : float, mm — Z extent of the cylindrical body
    head_style : str — "none" | "round" | "flat" | "knurled"
    head_diameter : float, mm — 0 ⇒ ``1.6 × diameter``
    head_height : float, mm — 0 ⇒ ``0.5 × diameter``
    chamfer_mm : float, mm — bevel both shaft ends
    groove : bool — adds a circumferential snap-ring groove near the
        bottom end
    """

    diameter: float = 6.0
    length: float = 90.0
    head_style: str = "round"
    head_diameter: float = 0.0
    head_height: float = 0.0
    chamfer_mm: float = 0.5
    groove: bool = False

    def validate(self) -> None:
        _require_positive("diameter", self.diameter)
        _require_positive("length", self.length)
        if self.head_style not in {"none", "round", "flat", "knurled"}:
            raise ComponentBuildError(
                f"head_style {self.head_style!r} not in "
                "{none, round, flat, knurled}"
            )
        if self.chamfer_mm < 0 or self.chamfer_mm * 2 >= self.diameter:
            raise ComponentBuildError("chamfer_mm out of range")

    def _resolved_head(self) -> tuple[float, float]:
        hd = self.head_diameter or 1.6 * self.diameter
        hh = self.head_height or 0.5 * self.diameter
        return hd, hh

    def _build_solid(self) -> bd.Part:
        r = self.diameter / 2.0
        h = self.length
        with bd.BuildPart() as p:
            bd.Cylinder(r, h)
            if self.chamfer_mm > 0:
                try:
                    edges = (
                        p.part.edges()
                        .filter_by(bd.GeomType.CIRCLE)
                        .group_by(bd.Axis.Z)
                    )
                    bd.chamfer(
                        list(edges[0]) + list(edges[-1]), length=self.chamfer_mm
                    )
                except Exception:  # noqa: BLE001
                    pass
            if self.head_style != "none":
                hd, hh = self._resolved_head()
                with bd.Locations((0, 0, h / 2.0 + hh / 2.0)):
                    if self.head_style == "round":
                        bd.Sphere(hd / 2.0)
                    elif self.head_style == "knurled":
                        # Approximate knurl by a chamfered cylinder.
                        bd.Cylinder(hd / 2.0, hh)
                    else:
                        bd.Cylinder(hd / 2.0, hh)
            if self.groove:
                # Snap-ring groove near the bottom end.
                gw = max(0.6, r * 0.18)
                gd = max(0.4, r * 0.20)
                z_centre = -h / 2.0 + h * 0.18
                with bd.BuildPart() as g:
                    with bd.Locations((0, 0, z_centre)):
                        bd.Cylinder(r * 1.05, gw)
                    with bd.Locations((0, 0, z_centre)):
                        bd.Cylinder(r - gd, gw * 1.4, mode=bd.Mode.SUBTRACT)
                p.part = p.part - g.part
        return p.part


_SHAFT_PARAM_ALIASES = {
    "od": "diameter",
    "outer_diameter": "diameter",
    "shaft_diameter": "diameter",
    "pin_diameter": "diameter",
    "shaft_length": "length",
    "depth": "length",
    "height": "length",
    "depth_mm": "length",
}

_SHAFT_PARAM_SCHEMA = {
    "diameter": "float, mm",
    "length": "float, mm",
    "head_style": "string in {none, round, flat, knurled}",
    "chamfer_mm": "float, mm — bevel both shaft ends",
    "groove": "bool — adds snap-ring groove",
}


@register(
    "hinge_shaft",
    aliases=("pintle_shaft", "hinge_pin_shaft", "pin_3d", "shaft_3d"),
    description="Hinge pin / pintle with chamfered ends and optional head/groove.",
    param_aliases=_SHAFT_PARAM_ALIASES,
    param_schema=_SHAFT_PARAM_SCHEMA,
)
def make_hinge_shaft(**kwargs) -> HingeShaft:
    return HingeShaft(**kwargs)


# ---------------------------------------------------------------------------
# HingeBracketC
# ---------------------------------------------------------------------------


@dataclass
class HingeBracketC(Component):
    """C-shaped hinge bracket: a mounting wall plus upper and lower
    extensions whose pintle-pin holes are real drilled cylinders, not
    extruded slots. The pin can pass through both extensions on a
    single Z axis.

    Coordinate frame: mounting wall sits in the YZ plane at -X, the
    extensions reach in +X. The pintle axis is at (mount_wall_offset,
    0, 0..) along Z.

    Parameters
    ----------
    mounting_wall_width : float, mm — wall extent in Y
    mounting_wall_height : float, mm — wall extent in Z
    extension_length : float, mm — how far each extension reaches in +X
    extension_width : float, mm — extension extent in Y
    extension_thickness : float, mm — extension extent in Z (each one)
    extension_gap : float, mm — Z gap between upper and lower extensions
    pin_diameter : float, mm — drill diameter at the hinge axis
    hole_offset_x : float, mm — where on the extension the hole sits
    barrel_diameter : float, mm — if > 0, adds a cylindrical barrel
        boss around the extension hole, giving the hinge axis a real
        cylindrical face on the bracket too
    """

    mounting_wall_width: float = 50.0
    mounting_wall_height: float = 80.0
    mounting_wall_thickness: float = 4.0
    extension_length: float = 35.0
    extension_width: float = 30.0
    extension_thickness: float = 4.0
    extension_gap: float = 50.0
    pin_diameter: float = 6.0
    hole_offset_x: float = 22.0
    barrel_diameter: float = 14.0

    def validate(self) -> None:
        for n in (
            "mounting_wall_width",
            "mounting_wall_height",
            "mounting_wall_thickness",
            "extension_length",
            "extension_width",
            "extension_thickness",
            "extension_gap",
            "pin_diameter",
            "hole_offset_x",
        ):
            _require_positive(n, getattr(self, n))
        if self.pin_diameter * 2 >= self.hole_offset_x:
            raise ComponentBuildError(
                "pin_diameter too large relative to hole_offset_x"
            )
        if self.barrel_diameter and self.barrel_diameter <= self.pin_diameter:
            raise ComponentBuildError(
                "barrel_diameter must be > pin_diameter"
            )

    def _build_solid(self) -> bd.Part:
        t = self.mounting_wall_thickness
        mw_w = self.mounting_wall_width
        mw_h = self.mounting_wall_height
        ext_l = self.extension_length
        ext_w = self.extension_width
        ext_t = self.extension_thickness
        gap = self.extension_gap
        pin_r = self.pin_diameter / 2.0
        hole_x = self.hole_offset_x
        with bd.BuildPart() as p:
            with bd.Locations((-t / 2.0, 0, 0)):
                bd.Box(t, mw_w, mw_h)
            for sign in (+1.0, -1.0):
                z_c = sign * (gap / 2.0 + ext_t / 2.0)
                with bd.Locations((ext_l / 2.0, 0, z_c)):
                    bd.Box(ext_l, ext_w, ext_t)
                if self.barrel_diameter > 0:
                    with bd.Locations((hole_x, 0, z_c)):
                        bd.Cylinder(self.barrel_diameter / 2.0, ext_t)
                with bd.Locations((hole_x, 0, z_c)):
                    bd.Cylinder(pin_r, ext_t * 1.5, mode=bd.Mode.SUBTRACT)
        return p.part


_BRACKETC_PARAM_ALIASES = {
    "width": "mounting_wall_width",
    "height": "mounting_wall_height",
    "thickness": "mounting_wall_thickness",
    "depth": "extension_length",
    "extension_gap_mm": "extension_gap",
    "od": "barrel_diameter",
}


@register(
    "hinge_bracket_c",
    aliases=("c_bracket", "main_member_bracket", "c_hinge_bracket"),
    description="C-shape hinge bracket with real drilled barrels at the pin axis.",
    param_aliases=_BRACKETC_PARAM_ALIASES,
    param_schema={
        "mounting_wall_width": "float, mm",
        "mounting_wall_height": "float, mm",
        "extension_gap": "float, mm",
        "extension_length": "float, mm",
        "pin_diameter": "float, mm",
        "barrel_diameter": "float, mm",
    },
)
def make_hinge_bracket_c(**kwargs) -> HingeBracketC:
    return HingeBracketC(**kwargs)


# ---------------------------------------------------------------------------
# Washer / Boss helpers
# ---------------------------------------------------------------------------


@dataclass
class Washer(Component):
    """Annular washer."""

    outer_diameter: float = 14.0
    inner_diameter: float = 6.5
    thickness: float = 1.5

    def validate(self) -> None:
        _require_positive("outer_diameter", self.outer_diameter)
        _require_positive("inner_diameter", self.inner_diameter)
        _require_positive("thickness", self.thickness)
        if self.inner_diameter >= self.outer_diameter:
            raise ComponentBuildError(
                "inner_diameter must be < outer_diameter"
            )

    def _build_solid(self) -> bd.Part:
        with bd.BuildPart() as p:
            bd.Cylinder(self.outer_diameter / 2.0, self.thickness)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(
                    self.inner_diameter / 2.0,
                    self.thickness * 1.05,
                    mode=bd.Mode.SUBTRACT,
                )
        return p.part


@register(
    "washer",
    aliases=("flat_washer", "thrust_washer"),
    description="Annular washer (ID/OD/thickness).",
    param_aliases={
        "od": "outer_diameter",
        "id": "inner_diameter",
        "bore": "inner_diameter",
        "depth": "thickness",
        "depth_mm": "thickness",
        "height": "thickness",
        "diameter": "outer_diameter",
        "diameter_mm": "outer_diameter",
    },
    param_schema={
        "outer_diameter": "float, mm",
        "inner_diameter": "float, mm",
        "thickness": "float, mm",
    },
)
def make_washer(**kwargs) -> Washer:
    return Washer(**kwargs)


@dataclass
class Boss(Component):
    """Cylindrical boss / pin-head puck."""

    diameter: float = 8.0
    height: float = 6.0
    chamfer_mm: float = 0.5

    def validate(self) -> None:
        _require_positive("diameter", self.diameter)
        _require_positive("height", self.height)
        if self.chamfer_mm < 0:
            raise ComponentBuildError("chamfer_mm must be >= 0")

    def _build_solid(self) -> bd.Part:
        with bd.BuildPart() as p:
            bd.Cylinder(self.diameter / 2.0, self.height)
            if self.chamfer_mm > 0:
                try:
                    edges = (
                        p.part.edges()
                        .filter_by(bd.GeomType.CIRCLE)
                        .group_by(bd.Axis.Z)
                    )
                    bd.chamfer(list(edges[-1]), length=self.chamfer_mm)
                except Exception:  # noqa: BLE001
                    pass
        return p.part


@register(
    "boss_3d",
    aliases=("hinge_boss", "stop_boss", "pin_head_boss"),
    description="Cylindrical boss with optional top chamfer.",
    param_aliases={
        "od": "diameter",
        "outer_diameter": "diameter",
        "depth": "height",
        "depth_mm": "height",
        "length": "height",
    },
    param_schema={
        "diameter": "float, mm",
        "height": "float, mm",
        "chamfer_mm": "float, mm",
    },
)
def make_boss_3d(**kwargs) -> Boss:
    return Boss(**kwargs)


__all__ = [
    "HingeKnuckle",
    "HingeLeafWithKnuckles",
    "HingeShaft",
    "HingeBracketC",
    "Washer",
    "Boss",
]
