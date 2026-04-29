"""Render a model from canonical viewpoints and compare to the patent figure.

Once the assembly solver produces a 3D model, the user wants to be
able to verify "from at least one camera angle, the rendered CAD looks
like the patent figure." This module renders four standard views
(top, front, side, isometric) plus the page-out axis the figure
classifier picked, and writes a side-by-side comparison composite.

We do NOT re-call the VLM for scoring — the user's instruction was
"do not chase the old VLM validator". Instead we report deterministic
silhouette-area and aspect-ratio similarity per view so the user can
see WHICH view is the best match without paying VLM tokens.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from claim2cad.visual_validator import (
    make_comparison_grid,
    render_step_to_line_drawing,
    render_step_to_solid,
)

logger = logging.getLogger(__name__)


_VIEW_PRESETS: dict[str, tuple[float, float]] = {
    # name: (elev_deg, azim_deg) for matplotlib mplot3d view_init.
    "top": (89.9, -90.0),
    "front": (0.0, -90.0),
    "right": (0.0, 0.0),
    "left": (0.0, 180.0),
    "iso": (25.0, 45.0),
    "iso2": (25.0, 135.0),
}


@dataclass
class ViewProjection:
    name: str
    elev_deg: float
    azim_deg: float
    render_path: Path
    silhouette_area_ratio: float = 0.0
    aspect_ratio: float = 1.0


@dataclass
class ProjectionReport:
    figure_id: str
    views: list[ViewProjection] = field(default_factory=list)
    best_view: str = ""
    best_aspect_score: float = 0.0
    comparison_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "figure_id": self.figure_id,
            "best_view": self.best_view,
            "best_aspect_score": self.best_aspect_score,
            "comparison_path": str(self.comparison_path) if self.comparison_path else None,
            "views": [
                {
                    "name": v.name,
                    "elev_deg": v.elev_deg,
                    "azim_deg": v.azim_deg,
                    "render_path": str(v.render_path),
                    "silhouette_area_ratio": v.silhouette_area_ratio,
                    "aspect_ratio": v.aspect_ratio,
                }
                for v in self.views
            ],
        }
        return d


# ---------------------------------------------------------------------------
# Image metrics
# ---------------------------------------------------------------------------


def _silhouette_metrics(image_path: Path) -> tuple[float, float]:
    """Return (ink_fraction, aspect_ratio) of the rendered drawing.

    ``ink_fraction`` = fraction of dark pixels (line strokes), measured
    on a thresholded grayscale.
    ``aspect_ratio`` = bounding-box width / height of the inked region.
    """
    img = Image.open(image_path).convert("L")
    arr = np.asarray(img)
    ink = arr < 200
    if not ink.any():
        return 0.0, 1.0
    rows = ink.any(axis=1)
    cols = ink.any(axis=0)
    r0, r1 = np.argmax(rows), len(rows) - 1 - np.argmax(rows[::-1])
    c0, c1 = np.argmax(cols), len(cols) - 1 - np.argmax(cols[::-1])
    h = max(1, r1 - r0)
    w = max(1, c1 - c0)
    return float(ink.sum()) / float(arr.size), w / h


def _aspect_match_score(figure_aspect: float, view_aspect: float) -> float:
    """1 when aspect ratios match, decaying toward 0 as they diverge."""
    if figure_aspect <= 0 or view_aspect <= 0:
        return 0.0
    ratio = min(figure_aspect, view_aspect) / max(figure_aspect, view_aspect)
    return ratio


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_canonical_views(
    *,
    step_path: Path,
    out_dir: Path,
    figure_path: Path,
    view_names: tuple[str, ...] = ("top", "front", "right", "iso"),
    resolution: int = 1024,
    style: str = "solid",
) -> ProjectionReport:
    """Render the canonical views, score each by silhouette aspect-ratio
    match against the patent figure, save a side-by-side comparison.

    ``style`` selects the renderer used for ``projection_*.png``:

      * ``"solid"`` (default since v11-21): light-gray faces + black
        silhouette/crease outlines. Best for assembly inspection.
      * ``"line"``: pure line-art (the V11-10 wireframe).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    fig_ink, fig_aspect = _silhouette_metrics(figure_path)

    views: list[ViewProjection] = []
    best_score = -1.0
    best_view = ""
    for name in view_names:
        if name not in _VIEW_PRESETS:
            continue
        elev, azim = _VIEW_PRESETS[name]
        png = out_dir / f"projection_{name}.png"
        try:
            if style == "solid":
                render_step_to_solid(
                    step_path,
                    png,
                    elev=elev,
                    azim=azim,
                    resolution=resolution,
                )
            else:
                render_step_to_line_drawing(
                    step_path,
                    png,
                    elev=elev,
                    azim=azim,
                    resolution=resolution,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not render %s: %s", name, exc)
            continue
        ink, aspect = _silhouette_metrics(png)
        score = _aspect_match_score(fig_aspect, aspect)
        view = ViewProjection(
            name=name,
            elev_deg=elev,
            azim_deg=azim,
            render_path=png,
            silhouette_area_ratio=ink,
            aspect_ratio=aspect,
        )
        if score > best_score:
            best_score = score
            best_view = name
        views.append(view)

    composite_path = out_dir / "projection_comparison.png"
    try:
        make_comparison_grid(
            [v.render_path for v in views],
            figure_path,
            composite_path,
            label_left="Patent figure",
            label_right="CAD canonical views",
            cell_px=480,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not write comparison grid: %s", exc)
        composite_path = None  # type: ignore[assignment]

    return ProjectionReport(
        figure_id=figure_path.stem,
        views=views,
        best_view=best_view,
        best_aspect_score=best_score,
        comparison_path=composite_path,
    )


__all__ = [
    "ViewProjection",
    "ProjectionReport",
    "render_canonical_views",
]
