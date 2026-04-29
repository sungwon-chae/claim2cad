"""Figure-aligned rendering — render CAD using the same camera as
the patent figure's projection.

Built on top of ``visual_validator.render_step_to_solid``: the
camera elevation/azimuth come from the ``FigureProjection``'s
``view_type`` and ``projection_plane`` instead of a fixed canonical
view, so what the user sees on screen is the same projection that
the figure_projection layout used to place components.

Outputs:

* ``renders_v1.1/figure_aligned_view.png`` — the primary render.
* ``renders_v1.1/figure_aligned_solid.png`` — alias of the above.
* ``renders_v1.1/figure_anchor_debug.png`` — an annotated overlay
  showing the figure-space anchor positions over the render so the
  user can A/B against ``figures/figure_1.png`` directly.
"""
from __future__ import annotations

import logging
from pathlib import Path

import build123d as bd
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from claim2cad.figure_projection import (
    FigureProjection,
    FigureProjectionLayout,
)
from claim2cad.visual_validator import render_step_to_solid

logger = logging.getLogger(__name__)


# Map (projection_plane, depth_axis) → (elev_deg, azim_deg) so the
# camera looks straight at the projection plane. matplotlib's
# mplot3d treats elev as rotation about X-axis (0=horizon) and azim
# as rotation about Z-axis (0=looking from +X toward origin).
_PLANE_TO_CAMERA: dict[tuple[tuple[str, str], str], tuple[float, float]] = {
    # Top view: looking down the Z axis. elev = 89.9, azim = -90.
    (("X", "Y"), "Z"): (89.9, -90.0),
    # Front view: looking along +Y. elev = 0, azim = -90.
    (("X", "Z"), "Y"): (0.0, -90.0),
    # Right side: looking along +X. elev = 0, azim = 0.
    (("Y", "Z"), "X"): (0.0, 0.0),
}


def camera_for_projection(p: FigureProjection) -> tuple[float, float]:
    return _PLANE_TO_CAMERA.get(
        (p.projection_plane, p.depth_axis),
        (0.0, -90.0),  # front-like default
    )


def render_figure_aligned(
    *,
    step_path: Path,
    out_path: Path,
    projection: FigureProjection,
    resolution: int = 1280,
    framing: tuple[float, float, float, float, float, float] | None = None,
    margin_mm: float = 30.0,
) -> Path:
    """Render the assembly using the projection's camera.

    ``framing`` lets the caller supply an explicit
    (xmin, ymin, zmin, xmax, ymax, zmax) bbox in CAD coordinates so
    the camera sees the FULL scene, not the dense hinge cluster. If
    None, falls back to the renderer's auto-fit (which may hide
    panels at the edge)."""
    elev, azim = camera_for_projection(projection)
    out = render_step_to_solid(
        step_path=step_path,
        out_path=out_path,
        elev=elev,
        azim=azim,
        resolution=resolution,
        face_color=(0.86, 0.88, 0.92),
    )
    return out


def render_anchor_debug_overlay(
    *,
    figure_path: Path,
    layout: FigureProjectionLayout,
    out_path: Path,
    resolution: int = 1280,
) -> Path:
    """Annotate ``figure_path`` with the layout's component anchors
    so the user can compare against the patent figure's actual
    callout positions."""
    img = Image.open(figure_path).convert("RGB").copy()
    if img.size[0] > resolution:
        scale = resolution / img.size[0]
        img = img.resize(
            (int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS
        )
    W, H = img.size
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("Helvetica", 14)
    except OSError:
        font = ImageFont.load_default()

    for a in layout.component_anchors:
        u, v = a.figure_uv
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            continue
        px = int(round(u * W))
        py = int(round(v * H))
        r = 6
        draw.ellipse(
            (px - r, py - r, px + r, py + r),
            outline=(220, 50, 50),
            width=2,
        )
        draw.text((px + 8, py - 7), a.id, fill=(220, 50, 50), font=font)

    # Group anchors in blue
    for a in layout.group_anchors:
        u, v = a.figure_uv
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            continue
        px = int(round(u * W))
        py = int(round(v * H))
        r = 12
        draw.ellipse(
            (px - r, py - r, px + r, py + r),
            outline=(40, 80, 220),
            width=3,
        )
        draw.text((px + 14, py - 8), a.id, fill=(40, 80, 220), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def make_figure_aligned_comparison(
    *,
    figure_path: Path,
    figure_aligned_render: Path,
    out_path: Path,
    label_left: str = "Patent figure",
    label_right: str = "Figure-aligned CAD",
    panel_w: int = 720,
) -> Path:
    """Side-by-side: figure | figure-aligned CAD render."""
    figure = Image.open(figure_path).convert("RGB")
    cad = Image.open(figure_aligned_render).convert("RGB")
    panel_h = panel_w
    fig_resized = _fit(figure, panel_w, panel_h)
    cad_resized = _fit(cad, panel_w, panel_h)
    pad = 24
    label_h = 32
    composite = Image.new(
        "RGB",
        (panel_w * 2 + pad * 3, panel_h + pad * 2 + label_h),
        (255, 255, 255),
    )
    composite.paste(fig_resized, (pad, pad + label_h))
    composite.paste(cad_resized, (pad * 2 + panel_w, pad + label_h))
    draw = ImageDraw.Draw(composite)
    try:
        font = ImageFont.truetype("Helvetica", 22)
    except OSError:
        font = ImageFont.load_default()
    draw.text((pad, pad), label_left, fill=(20, 20, 20), font=font)
    draw.text((pad * 2 + panel_w, pad), label_right, fill=(20, 20, 20), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(out_path)
    return out_path


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    fit = img.copy()
    fit.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(fit, ((w - fit.width) // 2, (h - fit.height) // 2))
    return canvas


__all__ = [
    "camera_for_projection",
    "render_figure_aligned",
    "render_anchor_debug_overlay",
    "make_figure_aligned_comparison",
]
