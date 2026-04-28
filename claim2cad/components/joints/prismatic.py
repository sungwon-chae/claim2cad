"""Prismatic (rail-and-slider) joint: rectangular rail with a sliding block.

Used for: linear stages, drawer slides, telescoping struts.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class PrismaticJoint(Component):
    """A linear rail with a slider riding on it (axis along Y).

    Parameters
    ----------
    rail_length : float (mm) — rail extent along Y.
    rail_width : float (mm) — rail extent along X (the cross-section width).
    rail_height : float (mm) — rail extent along Z.
    slider_length : float (mm) — slider extent along Y.
    slider_clearance : float (mm) — radial gap between rail and slider.
    """

    rail_length: float = 100.0
    rail_width: float = 20.0
    rail_height: float = 12.0
    slider_length: float = 40.0
    slider_clearance: float = 0.5

    def validate(self) -> None:
        _require_positive("rail_length", self.rail_length)
        _require_positive("rail_width", self.rail_width)
        _require_positive("rail_height", self.rail_height)
        _require_positive("slider_length", self.slider_length)
        if self.slider_clearance < 0:
            raise ComponentBuildError("slider_clearance must be >= 0")
        if self.slider_length >= self.rail_length:
            raise ComponentBuildError("slider_length must be < rail_length")

    def _build_solid(self) -> bd.Compound:
        with bd.BuildPart() as rail:
            bd.Box(self.rail_width, self.rail_length, self.rail_height)
        # Slider straddles the rail with a small clearance.
        c = self.slider_clearance
        slider_outer_w = self.rail_width + 2 * (c + 4.0)  # 4mm wall around clearance
        slider_outer_h = self.rail_height + (c + 4.0)
        with bd.BuildPart() as slider:
            with bd.Locations((0, 0, slider_outer_h / 2.0 - self.rail_height / 2.0)):
                bd.Box(slider_outer_w, self.slider_length, slider_outer_h)
            with bd.Locations((0, 0, 0)):
                bd.Box(self.rail_width + 2 * c, self.slider_length * 1.1, self.rail_height + c, mode=bd.Mode.SUBTRACT)
        rail.part.label = "rail"
        slider.part.label = "slider"
        return bd.Compound(label="prismatic_joint", children=[rail.part, slider.part])

    def mounting_points(self, solid: bd.Compound | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "rail_a": (0.0, -self.rail_length / 2.0, 0.0),
            "rail_b": (0.0, +self.rail_length / 2.0, 0.0),
            "slider_top": (0.0, 0.0, self.rail_height / 2.0 + 4.0),
        }


@register(
    "prismatic_joint",
    aliases=("rail_slider", "linear_rail", "slide", "linear_stage"),
    description="Rail-and-slider prismatic joint.",
)
def make_prismatic_joint(**kwargs) -> PrismaticJoint:
    return PrismaticJoint(**kwargs)


__all__ = ["PrismaticJoint"]
