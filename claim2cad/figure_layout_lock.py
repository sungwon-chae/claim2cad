"""V12-B — patent-family-specific figure-first layout lock.

The v1.1 ``figure_projection.py`` derives group anchors from the
**median** of their member callouts in figure UV space. That works
when the callouts span the visible figure region. It fails when
most callouts cluster on the mechanism in the right half of the
figure (US4807331A), because the door panel — which is the largest
visible feature on the LEFT — has zero callouts and therefore zero
votes for its group anchor. The result: door_panel's group_uv
medians to (0.56, 0.46) — center of the figure — which collides
with everything else.

This module fixes that with a **patent-family-specific lock**:

  1. A `FigureRegionMap` is read from JSON (one per family) that
     hard-codes (u, v, depth_band) for each major group AS THEY
     APPEAR IN THE FIGURE — not as the callout median.
  2. `apply_layout_lock` overrides the V11-23 group_anchors with
     these locked values, then re-distributes component anchors
     to sit on a small offset *inside* their group bbox (preserving
     the relative ordering from the label medians, but never
     letting them drift back to a single origin).
  3. A hard distance constraint ensures every projected CAD center
     stays within the group's planar bbox.

The lock is patent-family-specific by design. For US4807331A the
JSON lives at ``examples/real_patents/US4807331A_spring_loaded_hinge
/figure_layout_lock.json``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from claim2cad.figure_projection import (
    FigureAnchor,
    FigureProjection,
    FigureProjectionLayout,
)

logger = logging.getLogger(__name__)


@dataclass
class GroupRegion:
    """A rectangular region in figure UV space + a depth band for
    the out-of-plane axis.

    `center_uv` is the visual centroid of the group's geometry in
    the figure (NOT the median of its label callouts). `bbox_uv` is
    [u0, v0, u1, v1] — used as a hard constraint when placing
    components within the group.

    `depth_mm` is the centre depth on the projection's depth_axis;
    components in this group sit at depth_mm ± a small per-shape
    offset.
    """

    group_id: str
    center_uv: tuple[float, float]
    bbox_uv: tuple[float, float, float, float]
    depth_mm: float = 0.0
    note: str = ""

    def width_uv(self) -> float:
        return max(0.0, self.bbox_uv[2] - self.bbox_uv[0])

    def height_uv(self) -> float:
        return max(0.0, self.bbox_uv[3] - self.bbox_uv[1])

    def contains_uv(self, uv: tuple[float, float], *, slack: float = 0.0) -> bool:
        u, v = uv
        u0, v0, u1, v1 = self.bbox_uv
        return (u0 - slack) <= u <= (u1 + slack) and (v0 - slack) <= v <= (v1 + slack)


@dataclass
class FigureRegionMap:
    """All locked group regions for one patent family."""

    family_id: str
    regions: list[GroupRegion] = field(default_factory=list)
    notes: str = ""

    def by_id(self) -> dict[str, GroupRegion]:
        return {r.group_id: r for r in self.regions}

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "regions": [asdict(r) for r in self.regions],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FigureRegionMap":
        return cls(
            family_id=d.get("family_id", ""),
            regions=[
                GroupRegion(
                    group_id=r["group_id"],
                    center_uv=tuple(r["center_uv"]),  # type: ignore[arg-type]
                    bbox_uv=tuple(r["bbox_uv"]),  # type: ignore[arg-type]
                    depth_mm=float(r.get("depth_mm", 0.0)),
                    note=r.get("note", ""),
                )
                for r in d.get("regions", [])
            ],
            notes=d.get("notes", ""),
        )


def load_region_map(path: Path) -> FigureRegionMap:
    return FigureRegionMap.from_dict(json.loads(path.read_text("utf-8")))


def save_region_map(rmap: FigureRegionMap, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rmap.to_dict(), indent=2), encoding="utf-8")
    return path


def apply_layout_lock(
    *,
    layout: FigureProjectionLayout,
    region_map: FigureRegionMap,
    component_to_group: dict[str, str],
    enforce_bbox: bool = True,
) -> FigureProjectionLayout:
    """Re-anchor a FigureProjectionLayout against a locked region map.

    For every group present in `region_map`:
      1. Replace the group's `figure_uv` and `cad_anchor_mm` with the
         locked region centre.
      2. For each component in that group, clamp its figure_uv to
         the region bbox (when `enforce_bbox=True`). Components
         already inside the bbox keep their original UV.
      3. Recompute component cad_anchor_mm from the (clamped) UV
         using the projection, then add the group's depth_mm offset
         on the projection's depth axis.

    Components whose group is NOT in the region_map are left alone.
    """
    proj = layout.projection
    by_region = region_map.by_id()
    depth_axis_idx = {"X": 0, "Y": 1, "Z": 2}[proj.depth_axis]

    # 1. Replace group anchors.
    new_group_anchors: list[FigureAnchor] = []
    seen_groups: set[str] = set()
    for ga in layout.group_anchors:
        region = by_region.get(ga.id)
        if region is not None:
            new_pose = list(proj.uv_to_world(region.center_uv))
            new_pose[depth_axis_idx] = region.depth_mm
            new_group_anchors.append(
                FigureAnchor(
                    id=ga.id,
                    figure_uv=region.center_uv,
                    cad_anchor_mm=tuple(new_pose),  # type: ignore[arg-type]
                    note=f"locked region: {region.note}" if region.note else "locked region",
                )
            )
            seen_groups.add(ga.id)
        else:
            new_group_anchors.append(ga)
    # Add any locked groups missing from layout.
    for gid, region in by_region.items():
        if gid in seen_groups:
            continue
        new_pose = list(proj.uv_to_world(region.center_uv))
        new_pose[depth_axis_idx] = region.depth_mm
        new_group_anchors.append(
            FigureAnchor(
                id=gid,
                figure_uv=region.center_uv,
                cad_anchor_mm=tuple(new_pose),  # type: ignore[arg-type]
                note=f"locked region: {region.note}" if region.note else "locked region",
            )
        )

    # 2 + 3. Re-anchor components inside their locked region.
    new_component_anchors: list[FigureAnchor] = []
    for ca in layout.component_anchors:
        gid = component_to_group.get(ca.id)
        region = by_region.get(gid) if gid else None
        uv = ca.figure_uv
        notes = ca.note
        if region is not None:
            if enforce_bbox and not region.contains_uv(uv, slack=0.005):
                # Clamp to the bbox, preserving relative position.
                u0, v0, u1, v1 = region.bbox_uv
                u_clamped = min(max(uv[0], u0), u1)
                v_clamped = min(max(uv[1], v0), v1)
                # If the original UV was way outside the bbox, fall
                # back to the region centre rather than a corner.
                if abs(uv[0] - u_clamped) > 0.05 or abs(uv[1] - v_clamped) > 0.05:
                    u_clamped, v_clamped = region.center_uv
                    notes = "snapped to region centre (was outside)"
                else:
                    notes = "clamped to region bbox"
                uv = (u_clamped, v_clamped)
            new_pose = list(proj.uv_to_world(uv))
            new_pose[depth_axis_idx] = region.depth_mm
            new_component_anchors.append(
                FigureAnchor(
                    id=ca.id,
                    figure_uv=uv,
                    cad_anchor_mm=tuple(new_pose),  # type: ignore[arg-type]
                    note=notes,
                )
            )
        else:
            new_component_anchors.append(ca)

    return FigureProjectionLayout(
        projection=proj,
        component_anchors=new_component_anchors,
        group_anchors=new_group_anchors,
    )


def render_lock_debug_overlay(
    *,
    figure_path: Path,
    region_map: FigureRegionMap,
    layout: FigureProjectionLayout,
    out_path: Path,
) -> Path:
    """Draw the locked group regions over the patent figure, plus
    the per-component anchors after the lock has been applied.

    Each region gets a coloured rectangle + label; each component is
    a small dot in the same colour as its group.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(figure_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
        font_s = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 14)
    except Exception:  # noqa: BLE001
        font = font_s = ImageFont.load_default()

    palette = [
        (40, 80, 220),    # blue — door_panel
        (180, 60, 30),    # red-orange — fixed_frame
        (40, 180, 60),    # green — upper_hinge
        (200, 140, 30),   # orange — lower_hinge
        (140, 60, 220),   # purple — pintle_axis
        (210, 60, 160),   # pink — power_mechanism
        (90, 140, 160),   # teal — fasteners
    ]
    by_region = region_map.by_id()
    region_color: dict[str, tuple[int, int, int]] = {}
    for i, gid in enumerate(by_region):
        region_color[gid] = palette[i % len(palette)]

    W, H = img.size

    # Group bboxes (semi-transparent fill + outline).
    for gid, region in by_region.items():
        u0, v0, u1, v1 = region.bbox_uv
        x0, y0 = u0 * W, v0 * H
        x1, y1 = u1 * W, v1 * H
        col = region_color.get(gid, (90, 90, 90))
        draw.rectangle((x0, y0, x1, y1),
                       fill=col + (28,),
                       outline=col + (220,),
                       width=3)
        # Label at top-left of bbox.
        draw.text((x0 + 6, y0 + 4), gid, fill=col + (255,), font=font)
        # Centre marker.
        cx, cy = region.center_uv[0] * W, region.center_uv[1] * H
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8),
                     fill=col + (200,), outline=(20, 20, 20, 220), width=2)

    # Component anchors.
    cid_to_group_color: dict[str, tuple[int, int, int]] = {}
    for ca in layout.component_anchors:
        col = (90, 90, 90)
        for gid, region in by_region.items():
            if region.contains_uv(ca.figure_uv, slack=0.01):
                col = region_color.get(gid, col)
                cid_to_group_color[ca.id] = col
                break
        cx, cy = ca.figure_uv[0] * W, ca.figure_uv[1] * H
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4),
                     fill=col + (220,), outline=(0, 0, 0, 200), width=1)

    out = Image.alpha_composite(img, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)
    return out_path


__all__ = [
    "GroupRegion",
    "FigureRegionMap",
    "load_region_map",
    "save_region_map",
    "apply_layout_lock",
    "render_lock_debug_overlay",
]
