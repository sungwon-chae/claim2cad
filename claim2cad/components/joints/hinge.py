"""Leaf hinge: two leaves joined by interlocking knuckles around a pin.

This is the centerpiece component for US4807331A. Default parameters match
the geometry inferred from figure_1.png; the figure-to-CAD generator
overrides them based on VLM-extracted dimensions.

Layout convention
-----------------
- Pin axis runs along Z.
- Both leaves lie roughly in horizontal half-planes (Y > 0 and Y < 0 in the
  closed position) and share the pin at Y = 0.
- Knuckles are short cylinders centered on the pin axis, alternating between
  leaf A and leaf B.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class LeafHinge(Component):
    """Two-leaf knuckle hinge with a single pin.

    Parameters
    ----------
    leaf_length : float (mm) — extent of each leaf along Y (the away-from-pin axis).
    leaf_width  : float (mm) — extent of each leaf along Z (matches pin length).
    leaf_thickness : float (mm) — sheet thickness of each leaf in X.
    knuckle_count : int — total knuckle segments. Must be >= 3 (alternating).
    pin_diameter : float (mm) — through-pin diameter; the knuckle bore matches.
    knuckle_diameter : float (mm) — outer diameter of each knuckle.
    leaf_offset_y : float (mm) — distance from pin axis to leaf root (sets the
        knuckle's effective swing radius).
    """

    leaf_length: float = 80.0
    leaf_width: float = 60.0
    leaf_thickness: float = 3.0
    knuckle_count: int = 3
    pin_diameter: float = 6.0
    knuckle_diameter: float = 14.0
    leaf_offset_y: float = 7.0

    def validate(self) -> None:
        _require_positive("leaf_length", self.leaf_length)
        _require_positive("leaf_width", self.leaf_width)
        _require_positive("leaf_thickness", self.leaf_thickness)
        _require_positive("pin_diameter", self.pin_diameter)
        _require_positive("knuckle_diameter", self.knuckle_diameter)
        if self.knuckle_count < 3:
            raise ComponentBuildError("knuckle_count must be >= 3")
        if self.pin_diameter >= self.knuckle_diameter:
            raise ComponentBuildError(
                "pin_diameter must be smaller than knuckle_diameter"
            )

    def _knuckle_segment_length(self) -> float:
        return self.leaf_width / float(self.knuckle_count)

    def _build_solid(self) -> bd.Compound:
        seg_len = self._knuckle_segment_length()
        knuckle_r = self.knuckle_diameter / 2.0
        pin_r = self.pin_diameter / 2.0

        # Build leaf A (Y > 0) — half the knuckles plus the leaf flange.
        with bd.BuildPart() as leaf_a:
            # Leaf flange centered at (leaf_thickness/2, leaf_length/2 + offset, 0).
            # We orient the leaf with its long axis along Y, thickness along X.
            leaf_y_center = self.leaf_length / 2.0 + self.leaf_offset_y
            with bd.Locations((0, leaf_y_center, 0)):
                bd.Box(self.leaf_thickness, self.leaf_length, self.leaf_width)
            # Knuckles for leaf A: even-indexed segments (0, 2, 4, ...).
            for i in range(0, self.knuckle_count, 2):
                z_center = -self.leaf_width / 2.0 + (i + 0.5) * seg_len
                with bd.Locations((0, 0, z_center)):
                    bd.Cylinder(knuckle_r, seg_len)
            # Drill the pin bore through every knuckle on this leaf.
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(pin_r, self.leaf_width * 1.05, mode=bd.Mode.SUBTRACT)

        # Leaf B (Y < 0) — opposite half plus odd-indexed knuckles.
        with bd.BuildPart() as leaf_b:
            leaf_y_center = -(self.leaf_length / 2.0 + self.leaf_offset_y)
            with bd.Locations((0, leaf_y_center, 0)):
                bd.Box(self.leaf_thickness, self.leaf_length, self.leaf_width)
            for i in range(1, self.knuckle_count, 2):
                z_center = -self.leaf_width / 2.0 + (i + 0.5) * seg_len
                with bd.Locations((0, 0, z_center)):
                    bd.Cylinder(knuckle_r, seg_len)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(pin_r, self.leaf_width * 1.05, mode=bd.Mode.SUBTRACT)

        # Pin: a single cylinder spanning the full leaf width.
        with bd.BuildPart() as pin:
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(pin_r * 0.98, self.leaf_width)

        # Tag the sub-parts so consumers can pick them out by label if
        # needed. The compound itself gets re-labelled by Component.tag().
        leaf_a.part.label = "leaf_a"
        leaf_b.part.label = "leaf_b"
        pin.part.label = "pin"

        return bd.Compound(label="leaf_hinge", children=[leaf_a.part, leaf_b.part, pin.part])

    def mounting_points(self, solid: bd.Compound | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "pin_top": (0.0, 0.0, +self.leaf_width / 2.0),
            "pin_bottom": (0.0, 0.0, -self.leaf_width / 2.0),
            "leaf_a_far": (0.0, self.leaf_length + self.leaf_offset_y, 0.0),
            "leaf_b_far": (0.0, -(self.leaf_length + self.leaf_offset_y), 0.0),
        }


@register(
    "leaf_hinge",
    aliases=(
        "hinge",
        "lift_off_hinge",
        "knuckle_hinge",
        "hinge_assembly",
        "hinge_body_half_assembly",
    ),
    description="Two-leaf knuckle hinge with through pin.",
)
def make_leaf_hinge(**kwargs) -> LeafHinge:
    return LeafHinge(**kwargs)


__all__ = ["LeafHinge"]
