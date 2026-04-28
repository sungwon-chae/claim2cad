"""Spur gear with simplified involute-like teeth.

The teeth are not analytically correct involutes — they are alternating
trapezoids that read as gear teeth in renders. For v1.1 visual fidelity
this is sufficient: rendered images need to *look* like a spur gear, not
mesh against a real gear.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class SpurGear(Component):
    """Spur gear (axis along Z) with cosmetic involute-like teeth.

    Parameters
    ----------
    module : float (mm) — gear module (m). Pitch diameter = module * teeth.
    teeth : int — tooth count.
    thickness : float (mm) — face width along Z.
    bore_diameter : float (mm) — center bore. 0 = no bore.
    """

    module: float = 2.0
    teeth: int = 20
    thickness: float = 6.0
    bore_diameter: float = 6.0

    def validate(self) -> None:
        _require_positive("module", self.module)
        _require_positive("thickness", self.thickness)
        if self.teeth < 6:
            raise ComponentBuildError("teeth must be >= 6")
        if self.bore_diameter < 0:
            raise ComponentBuildError("bore_diameter must be >= 0")

    @property
    def pitch_radius(self) -> float:
        return self.module * self.teeth / 2.0

    @property
    def addendum(self) -> float:
        return self.module

    @property
    def dedendum(self) -> float:
        return 1.25 * self.module

    def _build_solid(self) -> bd.Part:
        rp = self.pitch_radius
        ro = rp + self.addendum
        ri = rp - self.dedendum
        # Tooth profile sketched in XY: radial trapezoid centered at angle 0.
        tooth_arc = 2 * math.pi / self.teeth
        # Tooth occupies half the pitch (the other half is the gap).
        tooth_half_arc_outer = tooth_arc * 0.20
        tooth_half_arc_inner = tooth_arc * 0.30
        # Build tooth polygon (inner-left, inner-right, outer-right, outer-left).
        # All angles relative to +X. Place mid-tooth at angle 0.
        def pt(r: float, a: float) -> tuple[float, float]:
            return (r * math.cos(a), r * math.sin(a))

        tooth_pts = [
            pt(ri, -tooth_half_arc_inner),
            pt(ri, +tooth_half_arc_inner),
            pt(ro, +tooth_half_arc_outer),
            pt(ro, -tooth_half_arc_outer),
        ]

        # Build a single tooth as a polygon extrusion centered at origin.
        with bd.BuildPart() as one_tooth:
            with bd.BuildSketch() as _sk:
                bd.Polygon(*tooth_pts, align=None)
            bd.extrude(amount=self.thickness)
        # Center the tooth in Z so it can be summed with the centered disc.
        bb = one_tooth.part.bounding_box()
        one_tooth_centered = one_tooth.part.translate((0, 0, -(bb.min.Z + bb.max.Z) / 2.0))

        # Compose: disc + N rotated copies of the tooth.
        with bd.BuildPart() as gear:
            bd.Cylinder(ri, self.thickness)
            for i in range(self.teeth):
                deg = math.degrees(i * tooth_arc)
                rotated = one_tooth_centered.rotate(bd.Axis.Z, deg)
                gear.part = gear.part + rotated
            if self.bore_diameter > 0:
                with bd.Locations((0, 0, 0)):
                    bd.Cylinder(self.bore_diameter / 2.0, self.thickness * 1.2, mode=bd.Mode.SUBTRACT)
        return gear.part

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "center": (0.0, 0.0, 0.0),
            "face_a": (0.0, 0.0, -self.thickness / 2.0),
            "face_b": (0.0, 0.0, +self.thickness / 2.0),
        }


@register(
    "spur_gear",
    aliases=("gear", "pinion", "spur"),
    description="Spur gear with cosmetic teeth.",
    param_aliases={
        "n_teeth": "teeth",
        "tooth_count": "teeth",
        "face_width": "thickness",
        "width": "thickness",
        "bore": "bore_diameter",
    },
    param_schema={
        "module": "float, mm — gear module (pitch dia = module*teeth)",
        "teeth": "int >= 6",
        "thickness": "float, mm — face width along Z",
        "bore_diameter": "float, mm — center bore (0 = no bore)",
    },
)
def make_spur_gear(**kwargs) -> SpurGear:
    return SpurGear(**kwargs)


__all__ = ["SpurGear"]
