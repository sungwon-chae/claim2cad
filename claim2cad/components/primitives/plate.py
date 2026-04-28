"""Rectangular plate with optional hole pattern and rounded corners.

Used for hinge leaves, mounting walls, base plates, sidewalls — any flat
sheet with bolt holes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
class Plate(Component):
    """A flat rectangular plate.

    Parameters
    ----------
    length : float (mm) — extent along X.
    width  : float (mm) — extent along Y.
    thickness : float (mm) — extent along Z. Plate is centered on origin.
    fillet_radius : float (mm) — corner radius (0 = sharp corners).
    hole_pattern  : HolePattern | None — through-holes drilled in Z.
    """

    length: float = 60.0
    width: float = 40.0
    thickness: float = 4.0
    fillet_radius: float = 0.0
    hole_pattern: Optional[HolePattern] = None

    def validate(self) -> None:
        _require_positive("length", self.length)
        _require_positive("width", self.width)
        _require_positive("thickness", self.thickness)
        if self.fillet_radius < 0:
            raise ComponentBuildError("fillet_radius must be >= 0")
        max_fillet = min(self.length, self.width) / 2.0 - 0.01
        if self.fillet_radius > max_fillet:
            raise ComponentBuildError(
                f"fillet_radius {self.fillet_radius} > max {max_fillet:.2f} for "
                f"plate {self.length}x{self.width}"
            )
        if self.hole_pattern is not None:
            _require_positive("hole_pattern.diameter", self.hole_pattern.diameter)
            if self.hole_pattern.diameter >= min(self.length, self.width):
                raise ComponentBuildError("hole diameter exceeds plate footprint")

    def _build_solid(self) -> bd.Part:
        with bd.BuildPart() as plate:
            if self.fillet_radius > 0:
                with bd.BuildSketch() as sk:
                    bd.RectangleRounded(self.length, self.width, self.fillet_radius)
                bd.extrude(amount=self.thickness)
                # Re-center on origin: extrude added in +Z; shift so the
                # plate is symmetric about Z = 0 to match the bare-Box
                # convention used elsewhere in the library.
                plate.part = plate.part.translate((0, 0, -self.thickness / 2.0))
            else:
                bd.Box(self.length, self.width, self.thickness)
            if self.hole_pattern is not None:
                positions = self.hole_pattern.resolved()
                if positions:
                    with bd.Locations(*[(x, y, 0) for x, y in positions]):
                        bd.Hole(self.hole_pattern.diameter / 2.0)
        return plate.part

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        points = {"center": (0.0, 0.0, 0.0)}
        if self.hole_pattern is not None:
            for i, (x, y) in enumerate(self.hole_pattern.resolved()):
                points[f"hole_{i}"] = (x, y, 0.0)
        return points


_PLATE_PARAM_ALIASES = {
    # VLM commonly emits these — route to canonical field names.
    "size_x": "length",
    "size_y": "width",
    "size_z": "thickness",
    "depth": "thickness",
    "height": "thickness",  # for a flat plate, "height" almost always means thickness
}

_PLATE_PARAM_SCHEMA = {
    "length": "float, mm — extent along X (the long axis)",
    "width": "float, mm — extent along Y",
    "thickness": "float, mm — extent along Z (the sheet thickness)",
    "fillet_radius": "float, mm — corner fillet radius (0 = sharp)",
}


@register(
    "plate",
    aliases=("flat_plate", "sheet", "wall", "mounting_wall", "base_plate"),
    description="Rectangular plate with optional hole pattern and rounded corners.",
    param_aliases=_PLATE_PARAM_ALIASES,
    param_schema=_PLATE_PARAM_SCHEMA,
)
def make_plate(**kwargs) -> Plate:
    return Plate(**kwargs)


@register(
    "leaf",
    aliases=("hinge_leaf", "leaf_plate", "leaf_flange"),
    description="Hinge leaf — a plate sized for a knuckle hinge.",
    param_aliases=_PLATE_PARAM_ALIASES,
    param_schema=_PLATE_PARAM_SCHEMA,
)
def make_leaf(**kwargs) -> Plate:
    """Defaults sized for the US4807331A leaves: 80x40x3 with 4 mounting holes."""
    defaults = dict(
        length=80.0,
        width=40.0,
        thickness=3.0,
        fillet_radius=2.0,
        hole_pattern=HolePattern(diameter=4.5, rows=2, cols=2, spacing_x=50.0, spacing_y=20.0),
    )
    defaults.update(kwargs)
    return Plate(**defaults)


__all__ = ["Plate", "HolePattern"]
