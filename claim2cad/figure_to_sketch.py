"""Figure → 2D outline polygon extractor.

The user's correct observation: when you have an engineering drawing
(a 2D figure), the right way to make CAD that matches is **trace the
silhouette in the drawing, then extrude it along Z**. That's how
sketch-and-extrude CAD has worked since AutoCAD 1982. Generating
arbitrary boxes/cylinders with VLM-guessed dimensions and *hoping* the
top view ends up looking like the figure is the wrong order of
operations.

This module extracts a 2D outline polygon for each numbered component
in a patent figure. The polygon is stored in **normalised figure
coordinates** ((x, y) in [0, 1] over the WHOLE figure_1.png, with
y=0 at the top — image convention). Downstream, ``sketch_to_extrusion``
rescales those coordinates into mm and extrudes the polygon along the
+Z axis to give it depth.

Two extraction strategies, in order of preference:

1. **VLM polygon trace** — ask Claude-4.7 vision to look at the
   per-component figure crop (already produced by
   ``claim2cad.figure_crops``) and return an ordered list of (x, y)
   points tracing the outline. Best for stylised patent drawings with
   hidden lines / hatching / dimension lines that confuse contour
   tracers.

2. **OpenCV contour fallback** — for crops where the VLM declines or
   produces a degenerate polygon, fall back to ``cv2.findContours`` on
   a thresholded crop and pick the largest external contour.

Both paths return a ``ComponentOutline`` with the polygon in normalised
figure coords + an extrusion depth hint + a small validation report.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from claim2cad.figure_crops import FigureCrop
from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------


@dataclass
class ComponentOutline:
    """One component's traced 2D outline + extrusion hint.

    ``polygon_norm`` is a list of (x, y) pairs in normalised figure
    coordinates, i.e. relative to the whole figure_1.png with origin at
    top-left, y growing downward. Closed (first vertex == last vertex
    not required; we close it on consumption). At least 3 points.

    ``extrude_depth_mm`` is how thick the extrusion is along +Z. The VLM
    estimates this from the part type (a sheet plate is ~3mm; a pin is
    its diameter; a knuckle is its width).
    """

    component_id: str
    figure_number: str
    polygon_norm: list[tuple[float, float]] = field(default_factory=list)
    extrude_depth_mm: float = 3.0
    z_offset_mm: float = 0.0
    holes_norm: list[list[tuple[float, float]]] = field(default_factory=list)
    source: str = "vlm"  # "vlm" | "opencv" | "fallback"
    notes: str = ""

    def is_valid(self) -> bool:
        if len(self.polygon_norm) < 3:
            return False
        # area sanity (don't accept a 1-pixel polygon)
        area = _polygon_area(self.polygon_norm)
        if area < 1e-5:
            return False
        return True


@dataclass
class OutlineSet:
    """All extracted outlines + a global figure scale."""

    figure_id: str
    figure_width_px: int
    figure_height_px: int
    figure_scale_mm: float = 200.0  # how many mm the longest axis represents
    outlines: list[ComponentOutline] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "figure_width_px": self.figure_width_px,
            "figure_height_px": self.figure_height_px,
            "figure_scale_mm": self.figure_scale_mm,
            "outlines": [asdict(o) for o in self.outlines],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutlineSet":
        outs = [
            ComponentOutline(
                component_id=o["component_id"],
                figure_number=o.get("figure_number", ""),
                polygon_norm=[tuple(p) for p in o.get("polygon_norm", [])],  # type: ignore[misc]
                extrude_depth_mm=float(o.get("extrude_depth_mm", 3.0)),
                z_offset_mm=float(o.get("z_offset_mm", 0.0)),
                holes_norm=[
                    [tuple(p) for p in h] for h in o.get("holes_norm", [])  # type: ignore[misc]
                ],
                source=o.get("source", "vlm"),
                notes=o.get("notes", ""),
            )
            for o in d.get("outlines", [])
        ]
        return cls(
            figure_id=d["figure_id"],
            figure_width_px=int(d["figure_width_px"]),
            figure_height_px=int(d["figure_height_px"]),
            figure_scale_mm=float(d.get("figure_scale_mm", 200.0)),
            outlines=outs,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _polygon_area(pts: Iterable[tuple[float, float]]) -> float:
    """Shoelace, |signed area|."""
    pl = list(pts)
    if len(pl) < 3:
        return 0.0
    s = 0.0
    n = len(pl)
    for i in range(n):
        x0, y0 = pl[i]
        x1, y1 = pl[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def _crop_box_norm(crop: FigureCrop) -> tuple[float, float, float, float]:
    """Normalised (x0, y0, x1, y1) of the crop within the full figure."""
    return crop.bbox_norm


def _local_to_global_norm(
    local_xy: tuple[float, float],
    crop_box: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Convert (lx, ly) in [0, 1] of the CROP to (gx, gy) in [0, 1] of the full figure."""
    lx, ly = local_xy
    x0, y0, x1, y1 = crop_box
    return (x0 + lx * (x1 - x0), y0 + ly * (y1 - y0))


# ---------------------------------------------------------------------------
# VLM-based extraction
# ---------------------------------------------------------------------------


_VLM_SYSTEM = (
    "You are tracing the 2D outline of ONE mechanical component in a "
    "patent line drawing. The image you see is a CROP of the figure "
    "around one numbered callout. Trace the outer boundary of the part "
    "as a closed polygon — IGNORE dimension lines, leader lines, "
    "centerlines, hatching, and the callout number itself. Return "
    "strict JSON."
)


_VLM_USER_TEMPLATE = """The image is a crop of figure {figure_number}
showing the component called "{label}" (kind: {kind}, category:
{category}). Patent: {patent_title}.

Trace the OUTER outline of this part (only the part itself, not its
neighbours) as a closed polygon. Ignore dimension lines, leader
arrows, centerlines, and hatching strokes.

Coordinate system: image-local NORMALISED coordinates over THIS CROP,
with (0, 0) at top-left of the crop and (1, 1) at bottom-right.

Return JSON with EXACTLY this structure:
{{
  "polygon": [[<x>, <y>], [<x>, <y>], ...],
  "holes": [[[<x>, <y>], [<x>, <y>], ...], ...],
  "extrude_depth_mm": <float, mm>,
  "z_offset_mm": <float, mm — vertical offset above the assembly base, 0 if unknown>,
  "notes": "<short comment>"
}}

Rules:
- 6 to 40 points in the outer polygon. Roughly evenly spaced. Last
  point need not equal first; the polygon is implicitly closed.
- Each "holes" entry is the outline of an interior hole (e.g. a
  pintle pin hole) inside the part. Empty list if no holes.
- "extrude_depth_mm" is the part's thickness perpendicular to the
  drawing plane. Plates are typically 2-5mm; pin diameters are 4-8mm;
  bracket walls are 3-4mm; substantial bodies up to 30mm.
- "z_offset_mm" — if the part sits above another (e.g. a leaf flange
  above the lower extension), say how high. 0 if it's at the base.
- All coordinates inside [0, 1].
- If the part outline isn't visible in the crop (label-only callout),
  return polygon: [] and notes:"label only".
"""


def extract_outline_via_vlm(
    *,
    crop: FigureCrop,
    component_id: str,
    label: str,
    kind: str,
    category: str,
    patent_title: str = "",
    task_type: str = "v11_outline_trace",
) -> ComponentOutline:
    """Ask the VLM to trace the component outline. Returns an outline
    with polygon already mapped to FULL-FIGURE normalised coordinates."""
    user = _VLM_USER_TEMPLATE.format(
        figure_number=crop.figure_number,
        label=label,
        kind=kind or "(unknown)",
        category=category or "(unknown)",
        patent_title=patent_title or "(unknown)",
    )
    raw = vision_completion(
        image_path=crop.crop_path,
        system_prompt=_VLM_SYSTEM,
        user_prompt=user,
        task_type=task_type,
    )
    poly_local = raw.get("polygon") or []
    holes_local = raw.get("holes") or []
    depth = float(raw.get("extrude_depth_mm", 3.0) or 3.0)
    z_off = float(raw.get("z_offset_mm", 0.0) or 0.0)
    notes = str(raw.get("notes", ""))

    if not poly_local or len(poly_local) < 3:
        return ComponentOutline(
            component_id=component_id,
            figure_number=crop.figure_number,
            polygon_norm=[],
            extrude_depth_mm=depth,
            z_offset_mm=z_off,
            source="vlm",
            notes=notes or "vlm declined / empty polygon",
        )

    crop_box = _crop_box_norm(crop)
    poly_global: list[tuple[float, float]] = []
    for p in poly_local:
        try:
            lx, ly = float(p[0]), float(p[1])
        except (TypeError, IndexError, ValueError):
            continue
        if not (0.0 <= lx <= 1.0 and 0.0 <= ly <= 1.0):
            # Allow slight overshoot from VLM rounding.
            lx = max(0.0, min(1.0, lx))
            ly = max(0.0, min(1.0, ly))
        poly_global.append(_local_to_global_norm((lx, ly), crop_box))

    holes_global: list[list[tuple[float, float]]] = []
    for hole in holes_local:
        if not isinstance(hole, list) or len(hole) < 3:
            continue
        gh: list[tuple[float, float]] = []
        for p in hole:
            try:
                lx, ly = float(p[0]), float(p[1])
            except (TypeError, IndexError, ValueError):
                continue
            lx = max(0.0, min(1.0, lx))
            ly = max(0.0, min(1.0, ly))
            gh.append(_local_to_global_norm((lx, ly), crop_box))
        if len(gh) >= 3:
            holes_global.append(gh)

    return ComponentOutline(
        component_id=component_id,
        figure_number=crop.figure_number,
        polygon_norm=poly_global,
        extrude_depth_mm=depth,
        z_offset_mm=z_off,
        holes_norm=holes_global,
        source="vlm",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# OpenCV-based fallback
# ---------------------------------------------------------------------------


def extract_outline_via_opencv(
    *,
    crop: FigureCrop,
    component_id: str,
    target_points: int = 24,
) -> ComponentOutline:
    """Fallback: threshold the crop and pick the largest external contour.

    Less reliable than the VLM path on busy patent drawings (it can lock
    onto a callout-number outline or a hatching block instead of the
    part), but cheap and offline.
    """
    try:
        import cv2  # local import — opencv is heavy
    except Exception as exc:  # noqa: BLE001
        logger.warning("opencv import failed: %s", exc)
        return ComponentOutline(
            component_id=component_id,
            figure_number=crop.figure_number,
            polygon_norm=[],
            source="fallback",
            notes=f"opencv unavailable: {exc}",
        )

    img = np.array(Image.open(crop.crop_path).convert("L"))
    # Patent lines are dark; threshold to find ink pixels.
    _, bw = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
    # Light dilation to close small gaps between line segments.
    kernel = np.ones((3, 3), np.uint8)
    bw = cv2.dilate(bw, kernel, iterations=1)
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)
    if not contours:
        return ComponentOutline(
            component_id=component_id,
            figure_number=crop.figure_number,
            polygon_norm=[],
            source="opencv",
            notes="no contours detected",
        )
    contours.sort(key=lambda c: -cv2.contourArea(c))
    cnt = contours[0]
    # Approximate to ~target_points vertices.
    eps = 0.01 * cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, eps, True)
    h, w = bw.shape
    poly_local: list[tuple[float, float]] = [
        (float(p[0][0]) / w, float(p[0][1]) / h) for p in approx
    ]
    if len(poly_local) < 3:
        return ComponentOutline(
            component_id=component_id,
            figure_number=crop.figure_number,
            polygon_norm=[],
            source="opencv",
            notes=f"only {len(poly_local)} vertices",
        )
    crop_box = _crop_box_norm(crop)
    poly_global = [_local_to_global_norm(p, crop_box) for p in poly_local]
    return ComponentOutline(
        component_id=component_id,
        figure_number=crop.figure_number,
        polygon_norm=poly_global,
        extrude_depth_mm=3.0,
        source="opencv",
        notes=f"opencv contour, {len(poly_local)} verts",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def extract_outlines_for_components(
    *,
    figure_path: Path,
    component_crops: dict[str, FigureCrop],
    ir_components: dict[str, dict[str, Any]],
    patent_title: str = "",
    figure_scale_mm: float = 200.0,
    use_vlm: bool = True,
) -> OutlineSet:
    """Extract one outline per (component_id → figure_crop). Falls back
    to OpenCV when VLM result is empty/invalid."""
    img = Image.open(figure_path)
    out = OutlineSet(
        figure_id=figure_path.stem,
        figure_width_px=img.size[0],
        figure_height_px=img.size[1],
        figure_scale_mm=figure_scale_mm,
        outlines=[],
    )
    for cid, crop in component_crops.items():
        ir = ir_components.get(cid, {})
        outline: ComponentOutline | None = None
        if use_vlm:
            try:
                outline = extract_outline_via_vlm(
                    crop=crop,
                    component_id=cid,
                    label=ir.get("label", cid),
                    kind=ir.get("kind", ""),
                    category=ir.get("category", ""),
                    patent_title=patent_title,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("VLM outline failed for %s: %s", cid, exc)
                outline = None
        if outline is None or not outline.is_valid():
            cv = extract_outline_via_opencv(crop=crop, component_id=cid)
            if cv.is_valid():
                outline = cv
            elif outline is None:
                outline = cv
        out.outlines.append(outline)
    return out


__all__ = [
    "ComponentOutline",
    "OutlineSet",
    "extract_outline_via_vlm",
    "extract_outline_via_opencv",
    "extract_outlines_for_components",
]
