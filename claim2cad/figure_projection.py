"""Figure-projection coordinate model — patent figure as the primary
geometric constraint.

The previous (v11-19..22) layer used scaffold groups with *canonical*
origins picked by patent-family heuristic. Components within a group
all collapsed to that origin plus a small jitter, so the chosen CAD
view's projection didn't track the actual layout in figure_1.png.

This module introduces a real projection constraint:

  * **FigureProjection** — view_type, projection_plane (which world
    axes (u, v) correspond to), scale_px_to_mm, origin_px / origin_mm.
    Knows how to convert a figure-space (u, v) anchor in normalised
    image coordinates into a world-space (x, y, z) anchor in mm,
    and the inverse projection.
  * **figure_anchors_for_components** — read figure_map.json's
    per-callout `approximate_position` and emit one anchor per
    IR component_id.
  * **group_anchors_from_components** — aggregate per-component
    anchors into per-scene-group anchors (median X / Z of members).
  * **save_figure_projection** / **load_figure_projection** — JSON
    persistence at ``figure_projection.json``.

Coordinate convention:

  * Figure (u, v) is normalised image space, origin top-left, u
    grows right, v grows DOWN.
  * CAD world (x, y, z): x grows right, y grows BACK (away from
    viewer), z grows UP.
  * For a TOP view: (u, v) → (x, y_world), y is figure depth
    flipped (v=0 at back, v=1 at front), z is depth-of-extrusion.
  * For a FRONT view: (u, v) → (x, z), v is flipped (v=0 → z=top,
    v=1 → z=bottom).
  * For a RIGHT view: (u, v) → (-y, z) so up-on-figure is up-in-CAD
    AND looking-at-the-figure means looking along +X.
  * For an ISOMETRIC view: same mapping as FRONT (u → x, v → -z),
    with depth y filled by VLM hint or scaffold-group y offset.
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass
class FigureAnchor:
    """One (u, v) figure-space anchor for a component or group."""

    id: str
    figure_uv: tuple[float, float]
    cad_anchor_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    note: str = ""


@dataclass
class FigureProjection:
    """A 2-D projection model that maps figure (u, v) into CAD coords.

    Parameters
    ----------
    figure_id : str — e.g. ``"figure_1"``.
    view_type : str — top / front / right / left / iso / unknown.
    projection_plane : tuple[str, str] — which CAD axes (u, v) maps
        to. ``("X", "Z")`` means u → x and v → −z (v is flipped).
    figure_width_px / figure_height_px : int — source image size.
    scale_uv_to_mm : float — how many mm per unit of (u, v) along the
        widest figure axis. Defaults to a 200 mm assembly.
    origin_uv : tuple[float, float] — figure-space anchor of CAD
        world origin. Default is (0.5, 0.5) — figure centre.
    depth_axis : str — the CAD axis that is *out of the figure plane*
        (the one (u, v) does NOT map). Default Y.
    depth_value_mm : float — default depth (mm) of components that
        don't have an explicit y hint.
    """

    figure_id: str
    view_type: str = "iso"
    projection_plane: tuple[str, str] = ("X", "Z")
    figure_width_px: int = 0
    figure_height_px: int = 0
    scale_uv_to_mm: float = 200.0
    origin_uv: tuple[float, float] = (0.5, 0.5)
    depth_axis: str = "Y"
    depth_value_mm: float = 0.0

    def aspect(self) -> float:
        if self.figure_height_px <= 0:
            return 1.0
        return self.figure_width_px / self.figure_height_px

    def width_mm(self) -> float:
        # Map full image width to scale_uv_to_mm scaled by aspect.
        a = self.aspect()
        if a >= 1.0:
            return self.scale_uv_to_mm
        return self.scale_uv_to_mm * a

    def height_mm(self) -> float:
        a = self.aspect()
        if a >= 1.0:
            return self.scale_uv_to_mm / a
        return self.scale_uv_to_mm

    def uv_to_world(
        self,
        uv: tuple[float, float],
        *,
        depth_mm: float | None = None,
    ) -> tuple[float, float, float]:
        """Map a normalised (u, v) figure point to CAD (x, y, z).

        The (u, v) → CAD axis pair is given by ``self.projection_plane``.
        ``depth_mm`` overrides ``self.depth_value_mm`` for the
        out-of-plane axis."""
        u, v = float(uv[0]), float(uv[1])
        u0, v0 = self.origin_uv
        w_mm = self.width_mm()
        h_mm = self.height_mm()
        # u-axis (image x) → first projection axis
        # v-axis (image y) → second projection axis (flipped: v=0 top)
        first = (u - u0) * w_mm
        second = (v0 - v) * h_mm
        ax_u, ax_v = self.projection_plane
        coords = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        coords[ax_u] = first
        coords[ax_v] = second
        depth = self.depth_value_mm if depth_mm is None else float(depth_mm)
        coords[self.depth_axis] = depth
        return (coords["X"], coords["Y"], coords["Z"])

    def world_to_uv(
        self,
        xyz: tuple[float, float, float],
    ) -> tuple[float, float]:
        """Inverse projection. Useful for diagnostics."""
        ax_u, ax_v = self.projection_plane
        idx = {"X": 0, "Y": 1, "Z": 2}
        first = xyz[idx[ax_u]]
        second = xyz[idx[ax_v]]
        u0, v0 = self.origin_uv
        w_mm = self.width_mm()
        h_mm = self.height_mm()
        u = u0 + first / max(w_mm, 1e-9)
        v = v0 - second / max(h_mm, 1e-9)
        return (u, v)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureProjection":
        return cls(
            figure_id=d.get("figure_id", "figure_1"),
            view_type=d.get("view_type", "iso"),
            projection_plane=tuple(d.get("projection_plane", ("X", "Z"))),  # type: ignore[arg-type]
            figure_width_px=int(d.get("figure_width_px", 0)),
            figure_height_px=int(d.get("figure_height_px", 0)),
            scale_uv_to_mm=float(d.get("scale_uv_to_mm", 200.0)),
            origin_uv=tuple(d.get("origin_uv", (0.5, 0.5))),  # type: ignore[arg-type]
            depth_axis=d.get("depth_axis", "Y"),
            depth_value_mm=float(d.get("depth_value_mm", 0.0)),
        )


@dataclass
class FigureProjectionLayout:
    """Full layout artefact: projection + per-component anchors +
    per-group anchors."""

    projection: FigureProjection
    component_anchors: list[FigureAnchor] = field(default_factory=list)
    group_anchors: list[FigureAnchor] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection": self.projection.to_dict(),
            "component_anchors": [asdict(a) for a in self.component_anchors],
            "group_anchors": [asdict(a) for a in self.group_anchors],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureProjectionLayout":
        return cls(
            projection=FigureProjection.from_dict(d["projection"]),
            component_anchors=[
                FigureAnchor(
                    id=a["id"],
                    figure_uv=tuple(a["figure_uv"]),  # type: ignore[arg-type]
                    cad_anchor_mm=tuple(a["cad_anchor_mm"]),  # type: ignore[arg-type]
                    note=a.get("note", ""),
                )
                for a in d.get("component_anchors", [])
            ],
            group_anchors=[
                FigureAnchor(
                    id=a["id"],
                    figure_uv=tuple(a["figure_uv"]),  # type: ignore[arg-type]
                    cad_anchor_mm=tuple(a["cad_anchor_mm"]),  # type: ignore[arg-type]
                    note=a.get("note", ""),
                )
                for a in d.get("group_anchors", [])
            ],
        )


# ---------------------------------------------------------------------------
# Helpers — map view classification → projection plane
# ---------------------------------------------------------------------------


_VIEW_PLANE: dict[str, tuple[tuple[str, str], str]] = {
    # view_kind → (projection_plane, depth_axis)
    "top": (("X", "Y"), "Z"),  # u→X, v→-Y; depth Z
    "bottom": (("X", "Y"), "Z"),
    "front": (("X", "Z"), "Y"),
    "back": (("X", "Z"), "Y"),
    "right": (("Y", "Z"), "X"),
    "left": (("Y", "Z"), "X"),
    "iso": (("X", "Z"), "Y"),  # treat ISO as front-like for layout
    "isometric": (("X", "Z"), "Y"),
    "exploded": (("X", "Z"), "Y"),
    "sectional": (("X", "Z"), "Y"),
    "perspective": (("X", "Z"), "Y"),
    "unknown": (("X", "Z"), "Y"),
}


def projection_for_view(view_kind: str) -> tuple[tuple[str, str], str]:
    return _VIEW_PLANE.get(view_kind.lower(), _VIEW_PLANE["iso"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_projection(
    *,
    figure_id: str,
    view_kind: str,
    figure_width_px: int,
    figure_height_px: int,
    scale_uv_to_mm: float = 200.0,
    origin_uv: tuple[float, float] = (0.5, 0.5),
    depth_value_mm: float = 0.0,
) -> FigureProjection:
    plane, depth_axis = projection_for_view(view_kind)
    return FigureProjection(
        figure_id=figure_id,
        view_type=view_kind,
        projection_plane=plane,
        figure_width_px=figure_width_px,
        figure_height_px=figure_height_px,
        scale_uv_to_mm=scale_uv_to_mm,
        origin_uv=origin_uv,
        depth_axis=depth_axis,
        depth_value_mm=depth_value_mm,
    )


def figure_anchors_for_components(
    *,
    figure_map: dict[str, Any],
    projection: FigureProjection,
    component_depth_hints_mm: dict[str, float] | None = None,
) -> list[FigureAnchor]:
    """Read figure_map.vlm_labels and component_to_number, emit one
    FigureAnchor per IR component with the (u, v) and the
    projected CAD anchor."""
    component_to_number = figure_map.get("component_to_number", {}) or {}
    labels = figure_map.get("vlm_labels", []) or []
    pos_by_number: dict[str, tuple[float, float]] = {}
    for lab in labels:
        num = str(lab.get("number") or "").strip()
        pos = lab.get("approximate_position") or []
        if num and len(pos) >= 2:
            try:
                pos_by_number[num] = (float(pos[0]), float(pos[1]))
            except (TypeError, ValueError):
                continue

    anchors: list[FigureAnchor] = []
    depth_hints = component_depth_hints_mm or {}
    for cid, num in component_to_number.items():
        pos = pos_by_number.get(str(num))
        if pos is None:
            continue
        depth = depth_hints.get(cid)
        cad = projection.uv_to_world(pos, depth_mm=depth)
        anchors.append(FigureAnchor(id=cid, figure_uv=pos, cad_anchor_mm=cad))
    return anchors


def group_anchors_from_components(
    *,
    component_anchors: list[FigureAnchor],
    component_to_group: dict[str, str],
    projection: FigureProjection,
    group_depth_hints_mm: dict[str, float] | None = None,
    extra_groups: Iterable[str] = (),
) -> list[FigureAnchor]:
    """Aggregate per-component anchors into per-group anchors. Each
    group's (u, v) is the median of its members' (u, v); CAD anchor
    is reprojected from that median (so the group origin is on the
    same projection plane as its members)."""
    by_group: dict[str, list[FigureAnchor]] = {}
    for a in component_anchors:
        gid = component_to_group.get(a.id)
        if gid is None:
            continue
        by_group.setdefault(gid, []).append(a)

    out: list[FigureAnchor] = []
    seen = set()
    depth_hints = group_depth_hints_mm or {}
    for gid, members in by_group.items():
        seen.add(gid)
        u_med = statistics.median(a.figure_uv[0] for a in members)
        v_med = statistics.median(a.figure_uv[1] for a in members)
        depth = depth_hints.get(gid)
        cad = projection.uv_to_world((u_med, v_med), depth_mm=depth)
        out.append(
            FigureAnchor(
                id=gid,
                figure_uv=(u_med, v_med),
                cad_anchor_mm=cad,
                note=f"median of {len(members)} members",
            )
        )
    # Groups that have no members in figure_map (e.g. fasteners) get
    # a default anchor at figure centre, depth-shifted.
    for gid in extra_groups:
        if gid in seen:
            continue
        depth = depth_hints.get(gid)
        cad = projection.uv_to_world((0.5, 0.5), depth_mm=depth)
        out.append(
            FigureAnchor(
                id=gid,
                figure_uv=(0.5, 0.5),
                cad_anchor_mm=cad,
                note="default — no figure members",
            )
        )
    return out


def save_layout(layout: FigureProjectionLayout, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(layout.to_dict(), indent=2), encoding="utf-8")
    return path


def load_layout(path: Path) -> FigureProjectionLayout:
    return FigureProjectionLayout.from_dict(
        json.loads(path.read_text("utf-8"))
    )


__all__ = [
    "FigureAnchor",
    "FigureProjection",
    "FigureProjectionLayout",
    "build_projection",
    "figure_anchors_for_components",
    "group_anchors_from_components",
    "projection_for_view",
    "save_layout",
    "load_layout",
]
