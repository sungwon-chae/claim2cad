"""L-bracket and U-bracket primitives.

Used for: mounting brackets, U-shaped link members (US4807331A:24), pivot
holders, motor mounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import build123d as bd

from claim2cad.components.base import (
    Component,
    ComponentBuildError,
    HolePattern,
    _require_positive,
)
from claim2cad.components.library import register


@dataclass
class LBracket(Component):
    """L-shaped bracket: two perpendicular plates sharing one edge.

    Origin sits at the inner corner. Plate A lies in the XY plane (extending
    in +X), Plate B rises in the XZ plane (extending in +Z).

    Parameters
    ----------
    leg_a_length : extent of plate A in +X.
    leg_b_length : extent of plate B in +Z.
    width : common Y dimension.
    thickness : sheet thickness.
    """

    leg_a_length: float = 50.0
    leg_b_length: float = 50.0
    width: float = 30.0
    thickness: float = 4.0
    fillet_radius: float = 2.0
    hole_pattern_a: Optional[HolePattern] = None
    hole_pattern_b: Optional[HolePattern] = None

    def validate(self) -> None:
        _require_positive("leg_a_length", self.leg_a_length)
        _require_positive("leg_b_length", self.leg_b_length)
        _require_positive("width", self.width)
        _require_positive("thickness", self.thickness)

    def _build_solid(self) -> bd.Part:
        # Plate A: lies flat in XY, occupies (0..leg_a, -W/2..+W/2, 0..t).
        with bd.BuildPart() as bracket:
            with bd.Locations((self.leg_a_length / 2.0, 0, self.thickness / 2.0)):
                bd.Box(self.leg_a_length, self.width, self.thickness)
            # Plate B: stands vertical in XZ, footprint (0..t, -W/2..+W/2,
            # 0..leg_b).
            with bd.Locations((self.thickness / 2.0, 0, self.leg_b_length / 2.0)):
                bd.Box(self.thickness, self.width, self.leg_b_length)
            # Inner-corner fillet: along the Y axis at (t, 0, t).
            if self.fillet_radius > 0:
                shared_edges = [
                    e
                    for e in bracket.part.edges()
                    if abs(e.length - self.width) < 1e-3
                    and abs(e.center().X - self.thickness) < 1e-3
                    and abs(e.center().Z - self.thickness) < 1e-3
                ]
                if shared_edges:
                    bd.fillet(shared_edges, radius=min(self.fillet_radius, self.thickness * 0.9))
            # Drill leg-A holes in Z.
            if self.hole_pattern_a is not None:
                positions = self.hole_pattern_a.resolved()
                if positions:
                    with bd.Locations(
                        *[
                            (x + self.leg_a_length / 2.0 + self.thickness, y, self.thickness)
                            for x, y in positions
                        ]
                    ):
                        bd.Hole(self.hole_pattern_a.diameter / 2.0)
            # Drill leg-B holes in X.
            if self.hole_pattern_b is not None:
                positions = self.hole_pattern_b.resolved()
                if positions:
                    plane_b = bd.Plane.YZ.offset(self.thickness)
                    with bd.Locations(
                        *[
                            plane_b * bd.Location((x, y + self.leg_b_length / 2.0, 0))
                            for x, y in positions
                        ]
                    ):
                        bd.Hole(self.hole_pattern_b.diameter / 2.0)
        return bracket.part


@dataclass
class UBracket(Component):
    """U-shaped bracket: a base plate with two parallel side plates.

    Origin: center of base plate's top face. Sides rise in +Z.

    Parameters
    ----------
    base_length : extent of base plate along X.
    base_width : extent along Y (also the inner gap of the U).
    side_height : how far the sides rise in +Z.
    thickness : sheet thickness for all three plates.
    side_hole_diameter : optional through-hole drilled in both sides at
        (0, 0, side_z) — the pivot hole for a hinge pin. ``side_z`` is at
        ``side_height - side_hole_offset`` from the base.
    """

    base_length: float = 60.0
    base_width: float = 40.0
    side_height: float = 35.0
    thickness: float = 4.0
    side_hole_diameter: float = 0.0
    side_hole_offset: float = 8.0

    def validate(self) -> None:
        _require_positive("base_length", self.base_length)
        _require_positive("base_width", self.base_width)
        _require_positive("side_height", self.side_height)
        _require_positive("thickness", self.thickness)
        if self.side_hole_diameter < 0:
            raise ComponentBuildError("side_hole_diameter must be >= 0")
        if self.side_hole_diameter > 0 and self.side_hole_diameter >= min(
            self.base_length * 0.9, self.side_height * 0.9
        ):
            raise ComponentBuildError("side_hole_diameter too large for side plate")

    def _build_solid(self) -> bd.Part:
        with bd.BuildPart() as bracket:
            # Base plate: centered at origin, top face at z=0.
            with bd.Locations((0, 0, -self.thickness / 2.0)):
                bd.Box(self.base_length, self.base_width, self.thickness)
            # Two side plates rising in +Z.
            half_w = self.base_width / 2.0
            for sign in (-1.0, +1.0):
                with bd.Locations(
                    (0, sign * (half_w - self.thickness / 2.0), self.side_height / 2.0)
                ):
                    bd.Box(self.base_length, self.thickness, self.side_height)
            # Optional through-pin hole through both sides.
            if self.side_hole_diameter > 0:
                z_center = self.side_height - self.side_hole_offset
                with bd.Locations(
                    bd.Plane.XZ * bd.Location((0, z_center, 0))
                ):
                    bd.Hole(self.side_hole_diameter / 2.0, depth=self.base_width * 1.1)
        return bracket.part

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        z = self.side_height - self.side_hole_offset
        return {
            "center": (0.0, 0.0, 0.0),
            "pivot_axis_a": (0.0, -self.base_width / 2.0, z),
            "pivot_axis_b": (0.0, +self.base_width / 2.0, z),
        }


_L_BRACKET_PARAM_ALIASES = {
    "length": "leg_a_length",
    "height": "leg_b_length",
    "leg_length": "leg_a_length",
    "vertical_length": "leg_b_length",
    "horizontal_length": "leg_a_length",
    "depth": "width",
}

_L_BRACKET_PARAM_SCHEMA = {
    "leg_a_length": "float, mm — extent of plate A in +X (horizontal leg)",
    "leg_b_length": "float, mm — extent of plate B in +Z (vertical leg)",
    "width": "float, mm — common Y dimension",
    "thickness": "float, mm — sheet thickness",
    "fillet_radius": "float, mm — inner-corner fillet (0 = sharp)",
}


_U_BRACKET_PARAM_ALIASES = {
    "length": "base_length",
    "width": "base_width",
    "height": "side_height",
    "depth": "base_width",
    "size_x": "base_length",
    "size_y": "base_width",
    "size_z": "side_height",
    "leg_height": "side_height",
    "side_length": "side_height",
    "channel_width": "base_width",
    "wall_thickness": "thickness",
    "hole_diameter": "side_hole_diameter",
    "pin_hole_diameter": "side_hole_diameter",
}

_U_BRACKET_PARAM_SCHEMA = {
    "base_length": "float, mm — base plate extent along X",
    "base_width": "float, mm — base plate extent along Y (also the inner gap of the U)",
    "side_height": "float, mm — how far the sides rise in +Z",
    "thickness": "float, mm — sheet thickness for all three plates",
    "side_hole_diameter": "float, mm — pivot through-hole drilled in both sides (0 = no hole)",
    "side_hole_offset": "float, mm — distance from top of side to hole centre",
}


@register(
    "l_bracket",
    aliases=("angle_bracket", "corner_bracket"),
    description="L-shaped two-plate bracket.",
    param_aliases=_L_BRACKET_PARAM_ALIASES,
    param_schema=_L_BRACKET_PARAM_SCHEMA,
)
def make_l_bracket(**kwargs) -> LBracket:
    return LBracket(**kwargs)


@register(
    "u_bracket",
    aliases=(
        "u_link",
        "channel_bracket",
        "u_shaped_link_member",
        "clevis",
    ),
    description="U-shaped channel bracket with optional pivot hole.",
    param_aliases=_U_BRACKET_PARAM_ALIASES,
    param_schema=_U_BRACKET_PARAM_SCHEMA,
)
def make_u_bracket(**kwargs) -> UBracket:
    return UBracket(**kwargs)


__all__ = ["LBracket", "UBracket"]
