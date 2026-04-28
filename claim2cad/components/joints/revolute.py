"""Generic revolute joint: two members joined by a pivot pin.

The :class:`RevoluteJoint` is more general than :class:`LeafHinge`. It builds
two arms (rectangular slabs) joined at a single knuckle pivot. Useful for
linkage joints in robot arms, lever pivots, and spring-loaded mechanisms.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class RevoluteJoint(Component):
    """Two arms sharing a single pivot pin (axis along Z).

    Parameters
    ----------
    arm_a_length : extent of arm A along +Y from the pivot.
    arm_b_length : extent of arm B along -Y from the pivot.
    arm_width : width of each arm along Z.
    arm_thickness : thickness along X.
    pin_diameter : pivot pin diameter.
    knuckle_diameter : pivot bushing diameter.
    """

    arm_a_length: float = 60.0
    arm_b_length: float = 60.0
    arm_width: float = 20.0
    arm_thickness: float = 5.0
    pin_diameter: float = 6.0
    knuckle_diameter: float = 12.0

    def validate(self) -> None:
        _require_positive("arm_a_length", self.arm_a_length)
        _require_positive("arm_b_length", self.arm_b_length)
        _require_positive("arm_width", self.arm_width)
        _require_positive("arm_thickness", self.arm_thickness)
        _require_positive("pin_diameter", self.pin_diameter)
        _require_positive("knuckle_diameter", self.knuckle_diameter)
        if self.pin_diameter >= self.knuckle_diameter:
            raise ComponentBuildError("pin_diameter must be < knuckle_diameter")

    def _build_solid(self) -> bd.Compound:
        knuckle_r = self.knuckle_diameter / 2.0
        pin_r = self.pin_diameter / 2.0

        # Arm A: positioned to start at the knuckle face and extend +Y.
        with bd.BuildPart() as arm_a:
            with bd.Locations((0, knuckle_r + self.arm_a_length / 2.0, 0)):
                bd.Box(self.arm_thickness, self.arm_a_length, self.arm_width)
            # Knuckle on top half (Z > 0).
            with bd.Locations((0, 0, self.arm_width / 4.0)):
                bd.Cylinder(knuckle_r, self.arm_width / 2.0)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(pin_r, self.arm_width * 1.1, mode=bd.Mode.SUBTRACT)

        # Arm B: extends in -Y, knuckle on bottom half (Z < 0).
        with bd.BuildPart() as arm_b:
            with bd.Locations((0, -(knuckle_r + self.arm_b_length / 2.0), 0)):
                bd.Box(self.arm_thickness, self.arm_b_length, self.arm_width)
            with bd.Locations((0, 0, -self.arm_width / 4.0)):
                bd.Cylinder(knuckle_r, self.arm_width / 2.0)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(pin_r, self.arm_width * 1.1, mode=bd.Mode.SUBTRACT)

        # Pin spanning both halves.
        with bd.BuildPart() as pin:
            bd.Cylinder(pin_r * 0.98, self.arm_width)

        arm_a.part.label = "arm_a"
        arm_b.part.label = "arm_b"
        pin.part.label = "pivot_pin"
        return bd.Compound(label="revolute_joint", children=[arm_a.part, arm_b.part, pin.part])

    def mounting_points(self, solid: bd.Compound | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "pivot": (0.0, 0.0, 0.0),
            "arm_a_tip": (0.0, self.knuckle_diameter / 2.0 + self.arm_a_length, 0.0),
            "arm_b_tip": (0.0, -(self.knuckle_diameter / 2.0 + self.arm_b_length), 0.0),
        }


_REVOLUTE_PARAM_ALIASES = {
    "length": "arm_a_length",
    "width": "arm_width",
    "thickness": "arm_thickness",
    "height": "arm_width",
}


@register(
    "revolute_joint",
    aliases=("pivot", "pivot_joint", "rotary_joint"),
    description="Generic two-arm revolute joint.",
    param_aliases=_REVOLUTE_PARAM_ALIASES,
    param_schema={
        "arm_a_length": "float, mm — arm A extent in +Y from the pivot",
        "arm_b_length": "float, mm — arm B extent in -Y from the pivot",
        "arm_width": "float, mm — width of each arm along Z",
        "arm_thickness": "float, mm — thickness along X",
        "pin_diameter": "float, mm",
        "knuckle_diameter": "float, mm — bushing OD (must be > pin_diameter)",
    },
)
def make_revolute_joint(**kwargs) -> RevoluteJoint:
    return RevoluteJoint(**kwargs)


__all__ = ["RevoluteJoint"]
