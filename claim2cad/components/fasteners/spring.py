"""Helical compression spring.

Built by sweeping a circular wire cross-section along a true helical path.
This is the test case for "is this CAD library actually visually faithful"
— a spring rendered as a stack of donuts is a tell. A spring rendered as
a real helix is convincing.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register

_END_TYPES = {"open", "closed", "ground"}


@dataclass
class HelicalSpring(Component):
    """Compression spring with a true helical wire (axis along Z).

    Parameters
    ----------
    outer_diameter : float (mm) — wire-centerline diameter * 2 + wire diameter, approximately.
    wire_diameter : float (mm) — diameter of the wire stock.
    free_length : float (mm) — uncompressed overall length along Z.
    pitch : float (mm) — distance between consecutive coils. If 0, computed
        from ``active_coils`` instead.
    active_coils : float — number of full turns. Used to derive ``pitch``
        when ``pitch == 0``.
    end_type : "open" | "closed" | "ground" — cosmetic end treatment.
    """

    outer_diameter: float = 14.0
    wire_diameter: float = 1.4
    free_length: float = 30.0
    pitch: float = 0.0
    active_coils: float = 6.0
    end_type: str = "closed"

    def validate(self) -> None:
        _require_positive("outer_diameter", self.outer_diameter)
        _require_positive("wire_diameter", self.wire_diameter)
        _require_positive("free_length", self.free_length)
        if self.wire_diameter >= self.outer_diameter / 2.0:
            raise ComponentBuildError("wire_diameter too large for outer_diameter")
        if self.pitch < 0:
            raise ComponentBuildError("pitch must be >= 0")
        if self.pitch == 0 and self.active_coils <= 0:
            raise ComponentBuildError("either pitch or active_coils must be > 0")
        if self.end_type not in _END_TYPES:
            raise ComponentBuildError(
                f"end_type={self.end_type!r} not in {sorted(_END_TYPES)}"
            )

    @property
    def _resolved_pitch(self) -> float:
        if self.pitch > 0:
            return self.pitch
        return self.free_length / self.active_coils

    def _build_solid(self) -> bd.Part:
        # Helical wire centerline radius:
        wire_r = self.wire_diameter / 2.0
        coil_r = self.outer_diameter / 2.0 - wire_r
        pitch = self._resolved_pitch
        height = self.free_length

        helix = bd.Helix(pitch=pitch, height=height, radius=coil_r)
        with bd.BuildPart() as spring:
            with bd.BuildSketch(bd.Plane(origin=helix @ 0, z_dir=helix % 0)) as wire_section:
                bd.Circle(wire_r)
            bd.sweep(path=helix)
            # Re-center on origin in Z so the spring sits symmetric.
            bb = spring.part.bounding_box()
            dz = -(bb.min.Z + bb.max.Z) / 2.0
            spring.part = spring.part.translate((0, 0, dz))
            # End treatment: a flat disc cap at each end suggests a "closed
            # and ground" spring. ``open`` skips this.
            if self.end_type in {"closed", "ground"}:
                cap_t = wire_r * 1.4
                for sign in (-1.0, +1.0):
                    z_center = sign * (height / 2.0 - cap_t / 2.0)
                    with bd.BuildPart() as cap:
                        with bd.Locations((0, 0, z_center)):
                            bd.Cylinder(coil_r + wire_r, cap_t)
                        with bd.Locations((0, 0, z_center)):
                            bd.Cylinder(coil_r - wire_r, cap_t * 1.1, mode=bd.Mode.SUBTRACT)
                    spring.part = spring.part + cap.part
        return spring.part

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "top": (0.0, 0.0, +self.free_length / 2.0),
            "bottom": (0.0, 0.0, -self.free_length / 2.0),
            "center": (0.0, 0.0, 0.0),
        }


@register(
    "helical_spring",
    aliases=("spring", "compression_spring", "coil_spring"),
    description="Helical compression spring with true helical wire.",
    param_aliases={
        "od": "outer_diameter",
        "diameter": "outer_diameter",
        "wire_thickness": "wire_diameter",
        "length": "free_length",
        "height": "free_length",
        "n_coils": "active_coils",
        "coils": "active_coils",
        "turns": "active_coils",
    },
    param_schema={
        "outer_diameter": "float, mm",
        "wire_diameter": "float, mm — must be < outer_diameter / 2",
        "free_length": "float, mm — uncompressed length",
        "pitch": "float, mm — distance between coils (0 = derive from active_coils)",
        "active_coils": "float — number of full turns",
        "end_type": "string in {open, closed, ground}",
    },
)
def make_helical_spring(**kwargs) -> HelicalSpring:
    return HelicalSpring(**kwargs)


__all__ = ["HelicalSpring"]
