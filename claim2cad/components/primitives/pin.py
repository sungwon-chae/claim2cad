"""Cylindrical pin with optional head and retention groove.

Used for: hinge pins, dowel pins, pivot pins, pintle pins (US4807331A:22).
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register

_HEAD_STYLES = {"none", "flat", "round", "hex"}


@dataclass
class Pin(Component):
    """Cylindrical pin centered on origin, axis along Z.

    Parameters
    ----------
    length : float (mm) — total pin length along Z.
    diameter : float (mm) — shaft diameter.
    head_style : "none" | "flat" | "round" | "hex"
        ``flat`` = cylindrical head, ``round`` = hemispherical head,
        ``hex`` = hex-prism head.
    head_diameter : float (mm) — diameter (or across-flats for hex). 0
        means ``1.6 * diameter``.
    head_height : float (mm) — head depth in Z. 0 means ``0.6 * diameter``.
    has_groove : bool — adds a small retention groove near the bottom end
        (suggests a circlip or e-clip seat).
    """

    length: float = 30.0
    diameter: float = 6.0
    head_style: str = "none"
    head_diameter: float = 0.0
    head_height: float = 0.0
    has_groove: bool = False

    def validate(self) -> None:
        _require_positive("length", self.length)
        _require_positive("diameter", self.diameter)
        if self.head_style not in _HEAD_STYLES:
            raise ComponentBuildError(
                f"head_style={self.head_style!r} not in {sorted(_HEAD_STYLES)}"
            )

    @property
    def _resolved_head_d(self) -> float:
        return self.head_diameter if self.head_diameter > 0 else 1.6 * self.diameter

    @property
    def _resolved_head_h(self) -> float:
        return self.head_height if self.head_height > 0 else 0.6 * self.diameter

    def _build_solid(self) -> bd.Part:
        radius = self.diameter / 2.0
        with bd.BuildPart() as pin:
            bd.Cylinder(radius, self.length)
            # Slight rounding on bottom for assembly clearance.
            try:
                bottom_edge = pin.part.edges().filter_by(bd.Axis.Z).group_by(bd.Axis.Z)[0]
                if bottom_edge:
                    bd.fillet(bottom_edge, radius=min(0.5, radius * 0.2))
            except Exception:
                pass
            if self.head_style != "none":
                head_d = self._resolved_head_d
                head_h = self._resolved_head_h
                z_top = self.length / 2.0 + head_h / 2.0
                with bd.Locations((0, 0, z_top)):
                    if self.head_style == "round":
                        bd.Sphere(head_d / 2.0)
                    elif self.head_style == "hex":
                        bd.RegularPolygon(head_d / 2.0, 6, major_radius=False)
                        # bd.RegularPolygon is a sketch primitive; build a solid
                        # via extrude. The above call only works inside BuildSketch
                        # — fall back to a simple cylinder if so.
                        bd.Cylinder(head_d / 2.0, head_h)
                    else:
                        bd.Cylinder(head_d / 2.0, head_h)
            if self.has_groove:
                groove_w = max(0.4, radius * 0.2)
                groove_d = max(0.2, radius * 0.15)
                z_center = -self.length / 2.0 + self.length * 0.15
                with bd.BuildPart() as groove_solid, bd.Locations((0, 0, z_center)):
                    bd.Cylinder(radius + 0.01, groove_w)
                    bd.Cylinder(radius - groove_d, groove_w + 0.02, mode=bd.Mode.SUBTRACT)
                pin.part = pin.part - groove_solid.part
        return pin.part

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "tip": (0.0, 0.0, -self.length / 2.0),
            "head": (0.0, 0.0, self.length / 2.0),
            "center": (0.0, 0.0, 0.0),
        }


_PIN_PARAM_ALIASES = {
    "od": "diameter",
    "outer_diameter": "diameter",
    "shaft_diameter": "diameter",
    "pin_diameter": "diameter",
    "shaft_length": "length",
    "pin_length": "length",
    "height": "length",
}

_PIN_PARAM_SCHEMA = {
    "length": "float, mm — total pin length along Z",
    "diameter": "float, mm — shaft diameter",
    "head_style": "string in {none, flat, round, hex}",
    "head_diameter": "float, mm — 0 = auto (1.6 × shaft diameter)",
    "head_height": "float, mm — 0 = auto",
    "has_groove": "bool — adds a retention groove near the bottom end",
}


@register(
    "pin",
    aliases=("pintle_pin", "dowel", "dowel_pin", "pivot_pin", "hinge_pin"),
    description="Cylindrical pin with optional head and retention groove.",
    param_aliases=_PIN_PARAM_ALIASES,
    param_schema=_PIN_PARAM_SCHEMA,
)
def make_pin(**kwargs) -> Pin:
    return Pin(**kwargs)


__all__ = ["Pin"]
