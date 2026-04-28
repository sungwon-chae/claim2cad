"""Cylindrical rod with optional end features.

Covers: links, shafts, struts, axles, push rods. End styles:
``flat`` (default) | ``rounded`` | ``threaded`` | ``flat_face``.
"""
from __future__ import annotations

from dataclasses import dataclass

import build123d as bd

from claim2cad.components.base import Component, ComponentBuildError, _require_positive
from claim2cad.components.library import register

_END_STYLES = {"flat", "rounded", "threaded", "flat_face"}


@dataclass
class Rod(Component):
    """Cylindrical rod centered on origin, axis along Z.

    Parameters
    ----------
    length : float (mm) — overall length along Z.
    diameter : float (mm) — outer diameter.
    end_a_style / end_b_style : "flat" | "rounded" | "threaded" | "flat_face"
        ``flat`` = sharp end (default).
        ``rounded`` = hemispherical cap.
        ``threaded`` = visual thread cosmetic groove (not real threads).
        ``flat_face`` = a flat machined onto one side, suggesting a key flat.
    """

    length: float = 50.0
    diameter: float = 6.0
    end_a_style: str = "flat"
    end_b_style: str = "flat"

    def validate(self) -> None:
        _require_positive("length", self.length)
        _require_positive("diameter", self.diameter)
        for k, v in (("end_a_style", self.end_a_style), ("end_b_style", self.end_b_style)):
            if v not in _END_STYLES:
                raise ComponentBuildError(
                    f"{k}={v!r} not in {sorted(_END_STYLES)}"
                )

    def _build_solid(self) -> bd.Part:
        radius = self.diameter / 2.0
        with bd.BuildPart() as rod:
            bd.Cylinder(radius, self.length)
            # End A is at -length/2 (Z-min), End B at +length/2 (Z-max).
            self._apply_end_feature(rod, self.end_a_style, z_sign=-1.0)
            self._apply_end_feature(rod, self.end_b_style, z_sign=+1.0)
        return rod.part

    def _apply_end_feature(self, builder: bd.BuildPart, style: str, z_sign: float) -> None:
        radius = self.diameter / 2.0
        z_end = z_sign * self.length / 2.0
        if style == "rounded":
            with bd.Locations((0, 0, z_end)):
                bd.Sphere(radius)
        elif style == "threaded":
            # Cosmetic groove: subtract a thin torus-like ring.
            groove_w = max(0.4, radius * 0.15)
            groove_d = max(0.2, radius * 0.10)
            z_inner = z_end - z_sign * groove_w
            z_lo = min(z_end, z_inner)
            with bd.BuildPart() as groove_solid, bd.Locations((0, 0, (z_lo + z_lo + groove_w) / 2.0)):
                bd.Cylinder(radius, groove_w)
                bd.Cylinder(radius - groove_d, groove_w, mode=bd.Mode.SUBTRACT)
            builder.part = builder.part - groove_solid.part
        elif style == "flat_face":
            # Subtract a slab on +X side near this end.
            slab_len = min(self.length * 0.25, 8.0)
            slab_thick = max(0.5, radius * 0.4)
            z_center = z_end - z_sign * slab_len / 2.0
            with bd.BuildPart() as slab, bd.Locations((radius, 0, z_center)):
                bd.Box(slab_thick * 2, self.diameter * 1.1, slab_len)
            builder.part = builder.part - slab.part
        # "flat" leaves the end as a clean cylinder face.

    def mounting_points(self, solid: bd.Part | None = None) -> dict[str, tuple[float, float, float]]:
        return {
            "end_a": (0.0, 0.0, -self.length / 2.0),
            "end_b": (0.0, 0.0, +self.length / 2.0),
            "center": (0.0, 0.0, 0.0),
        }


@register(
    "rod",
    aliases=("shaft", "axle", "link_rod", "strut", "cylinder_rod"),
    description="Cylindrical rod with optional rounded / threaded / flat ends.",
)
def make_rod(**kwargs) -> Rod:
    return Rod(**kwargs)


__all__ = ["Rod"]
