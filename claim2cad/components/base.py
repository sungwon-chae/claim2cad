"""Component ABC and shared helpers.

A :class:`Component` is the smallest unit the figure-to-CAD generator can
place into an assembly. Every shipped library entry inherits from it. The
contract is intentionally narrow:

    component = LeafHinge(leaf_length=80, leaf_width=40, ...)
    solid = component.build()                # build123d Solid / Compound
    component.tag(solid, "leaf_a")           # sets .label for GLB naming
    bbox = component.bbox(solid)             # axis-aligned, in mm
    points = component.mounting_points(solid)# {name: (x, y, z)}

The base class enforces that all dimensions are mm-floats, validates them on
construction, and provides ``export_step``/``export_glb`` helpers that share
the v1.0 :func:`claim2cad.glb_naming.rename_glb_root_children` postprocess.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd

from claim2cad.glb_naming import rename_glb_root_children

logger = logging.getLogger(__name__)


class ComponentBuildError(RuntimeError):
    """Raised when a library component refuses its parameters or build123d
    fails to produce a valid solid."""


# Material → RGB color hint used by GLB exporter via build123d.Color.
MATERIAL_COLORS: dict[str, tuple[float, float, float]] = {
    "steel": (0.65, 0.67, 0.72),
    "aluminum": (0.78, 0.78, 0.80),
    "brass": (0.85, 0.70, 0.30),
    "plastic": (0.30, 0.55, 0.85),
    "rubber": (0.20, 0.20, 0.22),
    "default": (0.70, 0.70, 0.74),
}


@dataclass
class Component(ABC):
    """Abstract parameterized mechanical part.

    Subclasses declare their parameters as additional ``dataclass`` fields,
    override :meth:`_build_solid` (the actual build123d construction), and
    optionally override :meth:`mounting_points` to expose useful pivot or
    bolt-hole positions to the assembly stage.
    """

    material: str = "steel"
    name: str = ""  # Optional library-display name (not the component_id).

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------------
    # Subclass extension points
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_solid(self) -> bd.Part | bd.Compound:
        """Return a fresh build123d solid representing this component.

        Implementations must NOT mutate ``self``; calling :meth:`build` twice
        must produce equivalent solids.
        """

    def validate(self) -> None:
        """Optional override for parameter sanity checks. Raise
        :class:`ComponentBuildError` on bad input."""
        # Subclasses override; default is permissive.
        return

    def mounting_points(self, solid: bd.Part | bd.Compound | None = None) -> dict[str, tuple[float, float, float]]:
        """Named anchor points (mm). Default returns the bbox center; useful
        components override to expose pivot axes, bolt holes, etc."""
        s = solid if solid is not None else self.build()
        bb = s.bounding_box()
        cx = (bb.min.X + bb.max.X) / 2.0
        cy = (bb.min.Y + bb.max.Y) / 2.0
        cz = (bb.min.Z + bb.max.Z) / 2.0
        return {"center": (cx, cy, cz)}

    # ------------------------------------------------------------------
    # Standard helpers (concrete; rarely overridden)
    # ------------------------------------------------------------------

    def build(self) -> bd.Part | bd.Compound:
        """Public entry: invoke ``_build_solid``, attach color, return solid.

        Raises :class:`ComponentBuildError` if the subclass returns nothing
        or build123d throws.
        """
        try:
            solid = self._build_solid()
        except Exception as exc:  # build123d raises a variety of types
            raise ComponentBuildError(
                f"{type(self).__name__} build failed: {exc}"
            ) from exc
        if solid is None:
            raise ComponentBuildError(
                f"{type(self).__name__}._build_solid returned None"
            )
        # Attach color hint. build123d tolerates Color on Part/Compound; if
        # an underlying type does not, log and continue.
        try:
            r, g, b = MATERIAL_COLORS.get(self.material, MATERIAL_COLORS["default"])
            solid.color = bd.Color(r, g, b)
        except Exception as exc:  # noqa: BLE001 — color is best-effort
            logger.debug("Color hint skipped for %s: %s", type(self).__name__, exc)
        return solid

    def bbox(self, solid: bd.Part | bd.Compound | None = None) -> tuple[float, float, float, float, float, float]:
        """Axis-aligned bounding box ``(xmin, ymin, zmin, xmax, ymax, zmax)``."""
        s = solid if solid is not None else self.build()
        bb = s.bounding_box()
        return (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)

    @staticmethod
    def tag(solid: bd.Part | bd.Compound, component_id: str) -> bd.Part | bd.Compound:
        """Set ``solid.label`` to ``component_id`` so the GLB exporter can
        track it. Returns the same solid for chaining."""
        if not component_id:
            raise ValueError("component_id must be a non-empty string")
        solid.label = component_id
        return solid

    # ------------------------------------------------------------------
    # Export helpers — used by tests and the per-example generator
    # ------------------------------------------------------------------

    def export_step(self, path: Path | str, component_id: str | None = None) -> Path:
        """Export this component as a STEP file. Returns the resulting path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        solid = self.build()
        if component_id:
            self.tag(solid, component_id)
        bd.export_step(solid, str(path))
        return path

    def export_glb(self, path: Path | str, component_id: str | None = None) -> Path:
        """Export this component as a binary glTF file with the supplied
        component_id as the root node name. Returns the resulting path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        solid = self.build()
        if component_id:
            self.tag(solid, component_id)
        bd.export_gltf(solid, str(path), binary=True)
        if component_id:
            try:
                rename_glb_root_children(path, [component_id])
            except Exception as exc:  # noqa: BLE001 — rename is best-effort
                logger.warning("GLB rename failed for %s: %s", path, exc)
        return path


# ----------------------------------------------------------------------
# Small validators reused by subclasses
# ----------------------------------------------------------------------


def _require_positive(name: str, value: float) -> None:
    if value is None or value <= 0:
        raise ComponentBuildError(f"{name} must be > 0, got {value!r}")


def _require_nonneg(name: str, value: float) -> None:
    if value is None or value < 0:
        raise ComponentBuildError(f"{name} must be >= 0, got {value!r}")


@dataclass
class HolePattern:
    """Helper used by plates/brackets to describe a regular hole grid.

    ``positions`` is in *plate-local* mm. If supplied, ``rows``/``cols`` are
    ignored. Otherwise positions are computed from ``rows``, ``cols``,
    ``spacing_x``, ``spacing_y``, centered on the plate origin.
    """

    diameter: float = 4.0
    rows: int = 0
    cols: int = 0
    spacing_x: float = 20.0
    spacing_y: float = 20.0
    positions: list[tuple[float, float]] = field(default_factory=list)

    def resolved(self) -> list[tuple[float, float]]:
        if self.positions:
            return list(self.positions)
        if self.rows <= 0 or self.cols <= 0:
            return []
        xs = [
            (i - (self.cols - 1) / 2.0) * self.spacing_x for i in range(self.cols)
        ]
        ys = [
            (j - (self.rows - 1) / 2.0) * self.spacing_y for j in range(self.rows)
        ]
        return [(x, y) for y in ys for x in xs]


__all__ = [
    "Component",
    "ComponentBuildError",
    "HolePattern",
    "MATERIAL_COLORS",
    "_require_nonneg",
    "_require_positive",
]
