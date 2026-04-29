"""Leader-line detection for patent figure callouts.

Patent figures number each callout (e.g. ``22``, ``32``,
``39'``) with a digit text drawn in white space and a thin straight
**leader line** that extends to a point on the actual part. Hotspot
grounding wants the *part endpoint* of that leader, not the label
position.

This module implements deterministic leader-line detection:

  1. For each callout's ``approximate_position`` (centre of the
     label digits), define a search ROI around it.
  2. Use OpenCV's probabilistic Hough transform to find all line
     segments in the ROI.
  3. Filter to segments that touch (or come within ~10 px of) the
     label's small bbox AND extend at least ``min_length_px`` toward
     the part.
  4. The endpoint farther from the label is the candidate part
     anchor.
  5. Pick the longest valid candidate as the leader for that
     callout. Save (label_bbox_px, line_start_px, line_end_px,
     confidence, method) per callout.

When no leader is found, the callout's record is still emitted with
``confidence=0`` and ``method="none"`` so the downstream hotspot
generator can fall back gracefully.

The detector is deterministic, runs in <1 s on a 2320×3408 figure,
and uses only OpenCV + NumPy + Pillow (already in the venv). No VLM
calls, no paid API.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class LeaderLine:
    """One detected leader for one callout instance."""

    callout_number: str
    label_index: int  # which `vlm_labels[i]` produced this candidate
    label_position_uv: tuple[float, float]
    label_bbox_px: tuple[float, float, float, float]
    line_start_px: tuple[float, float] | None = None  # near the label
    line_end_px: tuple[float, float] | None = None    # farther = part
    length_px: float = 0.0
    confidence: float = 0.0
    method: str = "none"  # "hough" | "none"
    notes: str = ""


@dataclass
class LeaderLineSet:
    figure_id: str
    figure_path: str
    image_width_px: int
    image_height_px: int
    leaders: list[LeaderLine] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "figure_id": self.figure_id,
            "figure_path": self.figure_path,
            "image_width_px": self.image_width_px,
            "image_height_px": self.image_height_px,
            "leaders": [asdict(l) for l in self.leaders],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _label_bbox_px(
    centre_uv: tuple[float, float],
    image_width_px: int,
    image_height_px: int,
    *,
    radius_frac_x: float = 0.022,
    radius_frac_y: float = 0.011,
) -> tuple[float, float, float, float]:
    """Approximate label box around a callout's normalised centre."""
    cx = centre_uv[0] * image_width_px
    cy = centre_uv[1] * image_height_px
    rx = image_width_px * radius_frac_x
    ry = image_height_px * radius_frac_y
    return (
        max(0.0, cx - rx),
        max(0.0, cy - ry),
        min(image_width_px - 1.0, cx + rx),
        min(image_height_px - 1.0, cy + ry),
    )


def _segment_length(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _point_in_bbox(p: tuple[float, float], bbox: tuple[float, float, float, float], pad: float = 0.0) -> bool:
    return (
        bbox[0] - pad <= p[0] <= bbox[2] + pad
        and bbox[1] - pad <= p[1] <= bbox[3] + pad
    )


def _distance_point_to_bbox(
    p: tuple[float, float], bbox: tuple[float, float, float, float]
) -> float:
    """Shortest distance from point to bbox (0 if inside)."""
    dx = max(bbox[0] - p[0], 0.0, p[0] - bbox[2])
    dy = max(bbox[1] - p[1], 0.0, p[1] - bbox[3])
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _binary_image(figure_path: Path) -> np.ndarray:
    """Load figure as a binary uint8 image where ink = 255 and
    background = 0 (so OpenCV line detection works as expected)."""
    img = Image.open(figure_path)
    if img.mode == "1":
        arr = np.array(img.convert("L"), dtype=np.uint8)
    else:
        arr = np.array(img.convert("L"), dtype=np.uint8)
    # Threshold: anything below 200 → ink. Invert so ink = 255.
    bw = (arr < 200).astype(np.uint8) * 255
    return bw


def _detect_lines_in_roi(
    bw_full: np.ndarray,
    roi_bbox: tuple[int, int, int, int],
    *,
    min_line_length: int,
    max_line_gap: int,
) -> list[tuple[int, int, int, int]]:
    """Run probabilistic Hough on the ROI; return segments in
    full-image coordinates."""
    import cv2

    x0, y0, x1, y1 = roi_bbox
    roi = bw_full[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    lines = cv2.HoughLinesP(
        roi,
        rho=1,
        theta=np.pi / 180.0,
        threshold=18,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return []
    out: list[tuple[int, int, int, int]] = []
    for line in lines:
        for sx, sy, ex, ey in line:
            out.append((sx + x0, sy + y0, ex + x0, ey + y0))
    return out


def detect_leader_for_label(
    *,
    bw_full: np.ndarray,
    label_position_uv: tuple[float, float],
    image_width_px: int,
    image_height_px: int,
    callout_number: str,
    label_index: int,
    search_radius_px: int = 240,
    min_leader_length_px: int = 30,
    max_label_distance_px: float = 18.0,
    label_box_pad_px: float = 8.0,
) -> LeaderLine:
    """Find the best leader line for a single callout.

    Returns a LeaderLine with confidence 0 + method=none if no leader
    is found.
    """
    label_bbox = _label_bbox_px(
        label_position_uv, image_width_px, image_height_px
    )
    cx = (label_bbox[0] + label_bbox[2]) / 2.0
    cy = (label_bbox[1] + label_bbox[3]) / 2.0
    roi_x0 = max(0, int(cx - search_radius_px))
    roi_y0 = max(0, int(cy - search_radius_px))
    roi_x1 = min(image_width_px, int(cx + search_radius_px))
    roi_y1 = min(image_height_px, int(cy + search_radius_px))

    segments = _detect_lines_in_roi(
        bw_full,
        (roi_x0, roi_y0, roi_x1, roi_y1),
        min_line_length=min_leader_length_px,
        max_line_gap=8,
    )
    if not segments:
        return LeaderLine(
            callout_number=callout_number,
            label_index=label_index,
            label_position_uv=label_position_uv,
            label_bbox_px=label_bbox,
            method="none",
            notes="no Hough segments in ROI",
        )

    # For each segment, compute (a) which endpoint is closer to the
    # label, (b) length, (c) "label distance" = min(dist(p0, label),
    # dist(p1, label)). Keep candidates whose label distance is small
    # AND whose far endpoint is OUTSIDE the label box (so the leader
    # actually goes somewhere). Score = length × confidence_decay.
    candidates: list[tuple[float, LeaderLine]] = []
    for sx, sy, ex, ey in segments:
        p0 = (float(sx), float(sy))
        p1 = (float(ex), float(ey))
        d0 = _distance_point_to_bbox(p0, label_bbox)
        d1 = _distance_point_to_bbox(p1, label_bbox)
        # Prefer the endpoint nearer the label as the start.
        if d0 <= d1:
            label_end, part_end, label_dist = p0, p1, d0
        else:
            label_end, part_end, label_dist = p1, p0, d1
        if label_dist > max_label_distance_px:
            continue
        if _point_in_bbox(part_end, label_bbox, pad=label_box_pad_px):
            continue
        length = _segment_length(label_end, part_end)
        if length < min_leader_length_px:
            continue
        # Confidence: longer leader + closer to label = higher.
        conf = max(0.0, 1.0 - (label_dist / max_label_distance_px) * 0.5)
        conf *= min(1.0, length / max(60.0, min_leader_length_px * 2))
        score = length * conf
        candidates.append(
            (
                score,
                LeaderLine(
                    callout_number=callout_number,
                    label_index=label_index,
                    label_position_uv=label_position_uv,
                    label_bbox_px=label_bbox,
                    line_start_px=label_end,
                    line_end_px=part_end,
                    length_px=length,
                    confidence=round(conf, 3),
                    method="hough",
                    notes=f"label_dist={label_dist:.1f}px",
                ),
            )
        )
    if not candidates:
        return LeaderLine(
            callout_number=callout_number,
            label_index=label_index,
            label_position_uv=label_position_uv,
            label_bbox_px=label_bbox,
            method="none",
            notes=f"{len(segments)} segments rejected (label dist or length)",
        )
    candidates.sort(key=lambda t: -t[0])
    return candidates[0][1]


def detect_leaders_for_figure(
    *,
    figure_path: Path,
    figure_map: dict[str, Any],
    search_radius_px: int = 240,
    min_leader_length_px: int = 30,
) -> LeaderLineSet:
    """Detect leader lines for every callout in figure_map.vlm_labels.

    Each label's ``approximate_position`` produces ONE LeaderLine
    record (so duplicate callout numbers contribute multiple
    records, which is exactly what V11-36 needs to disambiguate
    upper vs lower hinge instances)."""
    img = Image.open(figure_path)
    W, H = img.size
    bw = _binary_image(figure_path)

    leaders: list[LeaderLine] = []
    labels = figure_map.get("vlm_labels", []) or []
    for i, lab in enumerate(labels):
        num = str(lab.get("number") or "").strip()
        pos = lab.get("approximate_position") or []
        if not num or len(pos) < 2:
            continue
        try:
            uv = (float(pos[0]), float(pos[1]))
        except (TypeError, ValueError):
            continue
        leader = detect_leader_for_label(
            bw_full=bw,
            label_position_uv=uv,
            image_width_px=W,
            image_height_px=H,
            callout_number=num,
            label_index=i,
            search_radius_px=search_radius_px,
            min_leader_length_px=min_leader_length_px,
        )
        leaders.append(leader)

    notes_parts: list[str] = []
    n_with_leader = sum(1 for l in leaders if l.method == "hough")
    notes_parts.append(
        f"detected {n_with_leader}/{len(leaders)} leader endpoints "
        f"({n_with_leader / max(len(leaders), 1) * 100:.0f}%)"
    )
    return LeaderLineSet(
        figure_id=figure_map.get("primary_figure", "figure_1"),
        figure_path=str(figure_path),
        image_width_px=W,
        image_height_px=H,
        leaders=leaders,
        notes="; ".join(notes_parts),
    )


def save_leaders(ls: LeaderLineSet, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ls.to_dict(), indent=2), encoding="utf-8")
    return path


def render_leader_debug_overlay(
    *,
    figure_path: Path,
    leaders: LeaderLineSet,
    out_path: Path,
    resolution: int = 1280,
) -> Path:
    """Annotate the figure with detected leader lines and label
    bboxes, colour-coded by detection success."""
    from PIL import ImageDraw, ImageFont

    img = Image.open(figure_path).convert("RGB").copy()
    if img.size[0] > resolution:
        scale = resolution / img.size[0]
        img = img.resize(
            (int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS
        )
    sx = img.size[0] / max(leaders.image_width_px, 1)
    sy = img.size[1] / max(leaders.image_height_px, 1)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("Helvetica", 11)
    except OSError:
        font = ImageFont.load_default()

    for l in leaders.leaders:
        x0, y0, x1, y1 = l.label_bbox_px
        bbox_rect = (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
        if l.method == "hough" and l.line_start_px and l.line_end_px:
            col = (40, 180, 60)  # green = leader detected
            draw.rectangle(bbox_rect, outline=(40, 120, 200), width=1)
            sxp = l.line_start_px[0] * sx
            syp = l.line_start_px[1] * sy
            exp = l.line_end_px[0] * sx
            eyp = l.line_end_px[1] * sy
            draw.line((sxp, syp, exp, eyp), fill=col, width=2)
            r = 5
            draw.ellipse(
                (exp - r, eyp - r, exp + r, eyp + r),
                outline=col,
                width=2,
            )
            draw.text(
                (exp + 6, eyp - 6),
                f"{l.callout_number} ({l.confidence:.2f})",
                fill=col,
                font=font,
            )
        else:
            col = (220, 60, 60)  # red = no leader, fallback to label
            draw.rectangle(bbox_rect, outline=col, width=2)
            draw.text(
                (bbox_rect[2] + 4, bbox_rect[1]),
                f"{l.callout_number} ?",
                fill=col,
                font=font,
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


__all__ = [
    "LeaderLine",
    "LeaderLineSet",
    "detect_leader_for_label",
    "detect_leaders_for_figure",
    "save_leaders",
    "render_leader_debug_overlay",
]
