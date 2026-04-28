"""Ball bearing: outer race + inner race + simplified ball cage.

The balls are full spheres distributed around the race centerline, exposed
through cosmetic cutouts on the side walls. Like the gear teeth, this is
visual-fidelity-grade, not mesh-and-roll grade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register


@dataclass
class BallBearing(Component):
    """Annular ball bearing (axis along Z).

    Parameters
    ----------
    outer_diameter : float (mm) — OD of the outer race.
    inner_diameter : float (mm) — bore (inside diameter of the inner race).
    thickness : float (mm) — overall depth along Z.
    ball_count : int — number of balls between the races.
    """

    outer_diameter: float = 22.0
    inner_diameter: float = 8.0
    thickness: float = 7.0
    ball_count: int = 7

    def validate(self) -> None:
        _require_positive("outer_diameter", self.outer_diameter)
        _require_positive("inner_diameter", self.inner_diameter)
        _require_positive("thickness", self.thickness)
        if self.inner_diameter >= self.outer_diameter:
            raise ComponentBuildError("inner_diameter must be < outer_diameter")
        if self.ball_count < 3:
            raise ComponentBuildError("ball_count must be >= 3")

    def _build_solid(self) -> bd.Compound:
        ro = self.outer_diameter / 2.0
        ri = self.inner_diameter / 2.0
        # Race radial widths and ball geometry.
        race_w = (ro - ri) * 0.30
        ball_r = (ro - ri) * 0.20
        ball_centerline = (ro + ri) / 2.0
        outer_race_inner = ro - race_w
        inner_race_outer = ri + race_w

        with bd.BuildPart() as outer_race:
            bd.Cylinder(ro, self.thickness)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(outer_race_inner, self.thickness * 1.2, mode=bd.Mode.SUBTRACT)
        with bd.BuildPart() as inner_race:
            bd.Cylinder(inner_race_outer, self.thickness)
            with bd.Locations((0, 0, 0)):
                bd.Cylinder(ri, self.thickness * 1.2, mode=bd.Mode.SUBTRACT)

        # Balls: spheres at the centerline radius, distributed around Z axis.
        balls: list[bd.Part] = []
        for i in range(self.ball_count):
            theta = 2 * math.pi * i / self.ball_count
            x = ball_centerline * math.cos(theta)
            y = ball_centerline * math.sin(theta)
            with bd.BuildPart() as ball:
                with bd.Locations((x, y, 0)):
                    bd.Sphere(ball_r)
            balls.append(ball.part)

        outer_race.part.label = "outer_race"
        inner_race.part.label = "inner_race"
        children = [outer_race.part, inner_race.part]
        for i, b in enumerate(balls):
            b.label = f"ball_{i}"
            children.append(b)
        return bd.Compound(label="ball_bearing", children=children)

    def mounting_points(self, solid: bd.Compound | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "center": (0.0, 0.0, 0.0),
            "shaft": (0.0, 0.0, 0.0),
        }


@register(
    "ball_bearing",
    aliases=("bearing", "rolling_bearing", "deep_groove_bearing"),
    description="Ball bearing with outer race, inner race, and balls.",
    param_aliases={
        "od": "outer_diameter",
        "id": "inner_diameter",
        "bore": "inner_diameter",
        "width": "thickness",
        "height": "thickness",
        "depth": "thickness",
    },
    param_schema={
        "outer_diameter": "float, mm — OD of the outer race",
        "inner_diameter": "float, mm — bore (must be < outer_diameter)",
        "thickness": "float, mm — overall depth along Z",
        "ball_count": "int >= 3",
    },
)
def make_ball_bearing(**kwargs) -> BallBearing:
    return BallBearing(**kwargs)


__all__ = ["BallBearing"]
