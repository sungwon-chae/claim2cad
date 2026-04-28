"""Crop a patent figure around each numbered callout.

The figure_map.json carries a list of ``vlm_labels``: numbered callouts and
their ``approximate_position`` in normalised image coordinates. This module
turns each entry into a Pillow Image cropped tightly around that location,
sized to capture the surrounding component geometry rather than just the
number itself.

Used by:
* ``claim2cad.figure_to_cad.analyze_figure`` to give the VLM tighter
  attention.
* ``claim2cad.vlm_codegen`` to provide a per-component visual reference
  when synthesising build123d code.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class FigureCrop:
    """One crop tied to a figure-callout number."""

    figure_number: str
    component_id: str | None
    crop_path: Path
    bbox_norm: tuple[float, float, float, float]  # x0, y0, x1, y1 in [0, 1]


def _bbox_around(
    pos: tuple[float, float],
    *,
    half_w: float,
    half_h: float,
) -> tuple[float, float, float, float]:
    cx, cy = pos
    x0 = max(0.0, cx - half_w)
    y0 = max(0.0, cy - half_h)
    x1 = min(1.0, cx + half_w)
    y1 = min(1.0, cy + half_h)
    return (x0, y0, x1, y1)


def crop_figure_for_label(
    figure_path: Path,
    pos_norm: tuple[float, float],
    out_path: Path,
    *,
    crop_radius: float = 0.18,
    annotate: str | None = None,
) -> Path:
    """Crop ``figure_path`` to a square-ish window around ``pos_norm`` and
    save to ``out_path``. Returns ``out_path`` for chaining."""
    img = Image.open(figure_path).convert("RGB")
    W, H = img.size
    x0, y0, x1, y1 = _bbox_around(pos_norm, half_w=crop_radius, half_h=crop_radius)
    box_px = (
        int(round(x0 * W)),
        int(round(y0 * H)),
        int(round(x1 * W)),
        int(round(y1 * H)),
    )
    crop = img.crop(box_px)
    if annotate:
        # Draw a small banner at the bottom with the annotation. Cheap label
        # so the VLM can see "fig#22" overlaid on the crop without parsing
        # the surrounding numbers.
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(crop)
        try:
            font = ImageFont.truetype("Helvetica", 24)
        except OSError:
            font = ImageFont.load_default()
        text = annotate
        text_w = int(draw.textlength(text, font=font))
        bar_h = 32
        bar_y = crop.height - bar_h
        draw.rectangle((0, bar_y, crop.width, crop.height), fill=(0, 0, 0))
        draw.text(
            ((crop.width - text_w) // 2, bar_y + 4),
            text,
            fill=(255, 255, 255),
            font=font,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out_path)
    return out_path


def crop_all_components(
    figure_path: Path,
    figure_map: dict[str, Any],
    *,
    out_dir: Path,
    crop_radius: float = 0.18,
    component_ids_only: Iterable[str] | None = None,
) -> list[FigureCrop]:
    """Iterate ``figure_map.vlm_labels`` and write a crop per labelled
    number. If ``figure_map.component_to_number`` is present we attach
    each crop to its component_id."""
    labels = figure_map.get("vlm_labels") or []
    component_to_number = figure_map.get("component_to_number") or {}
    number_to_component: dict[str, str] = {
        str(num): cid for cid, num in component_to_number.items()
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    crops: list[FigureCrop] = []
    seen: set[tuple[str, str | None]] = set()
    for lab in labels:
        num = str(lab.get("number") or "").strip()
        pos = lab.get("approximate_position") or []
        if not num or len(pos) < 2:
            continue
        cid = number_to_component.get(num)
        if component_ids_only is not None and cid not in component_ids_only:
            continue
        key = (num, cid)
        if key in seen:
            continue
        seen.add(key)
        bbox = _bbox_around(
            (float(pos[0]), float(pos[1])),
            half_w=crop_radius,
            half_h=crop_radius,
        )
        cid_part = f"_{cid}" if cid else ""
        out_path = out_dir / f"crop_fig{num}{cid_part}.png"
        annotate = f"fig#{num}" + (f" -> {cid}" if cid else "")
        crop_figure_for_label(
            figure_path,
            (float(pos[0]), float(pos[1])),
            out_path,
            crop_radius=crop_radius,
            annotate=annotate,
        )
        crops.append(
            FigureCrop(
                figure_number=num,
                component_id=cid,
                crop_path=out_path,
                bbox_norm=bbox,
            )
        )
    logger.info("Wrote %d figure crops to %s", len(crops), out_dir)
    return crops


def crops_by_component_id(crops: list[FigureCrop]) -> dict[str, FigureCrop]:
    """Return crop indexed by component_id (last write wins). Crops with no
    component binding are skipped."""
    out: dict[str, FigureCrop] = {}
    for c in crops:
        if c.component_id:
            out[c.component_id] = c
    return out


__all__ = [
    "FigureCrop",
    "crop_figure_for_label",
    "crop_all_components",
    "crops_by_component_id",
]
