"""V12-D — readable demo renderer with per-mesh styling.

The default `render_step_to_solid` paints every face with the same
flat colour. For US4807331A that means the door panel — which is a
big plate sitting in front of the hinge mechanism — completely
occludes the upper hinge bracket in the figure-aligned view.

This module adds a thin renderer that:

  * Tessellates each top-level child of the imported compound
    SEPARATELY so it can apply per-component styling.
  * Lets the caller pass a style table that maps component_id (or
    a glob pattern) to (rgba_face, alpha, layer). Panels get
    semi-transparent + a back layer; brackets/knuckles stay
    opaque + front layer.
  * Sorts the draw order so transparent meshes render LAST (after
    opaque ones), so the hinge mechanism shows through the door
    panel without z-fighting.
  * Optionally overlays component labels for debug renders only.

This is matplotlib-based by design — Claim2CAD already ships a
matplotlib pipeline and we don't want to add a heavy GL dependency
just for the demo. Quality is good enough for a README-grade demo
image.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import build123d as bd
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from claim2cad.visual_validator import (
    _camera_basis,
    _feature_edges,
    _tessellate_shape,
)

logger = logging.getLogger(__name__)


@dataclass
class MeshStyle:
    """Per-component render style."""

    pattern: str  # glob — matched against child.label
    rgb: tuple[float, float, float] = (0.86, 0.88, 0.92)
    alpha: float = 1.0
    layer: int = 1  # higher = drawn later = on top
    edges: bool = True
    edge_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.85)
    edge_width: float = 0.6


# Default style for the US4807331A demo. Panels get transparency
# so they don't hide the hinge mechanism behind them.
US4807331A_DEMO_STYLES: list[MeshStyle] = [
    # Panels — semi-transparent so the hinge shows through.
    MeshStyle(pattern="door_panel", rgb=(0.78, 0.82, 0.92),
              alpha=0.45, layer=4, edges=True,
              edge_color=(0.10, 0.20, 0.50, 0.80), edge_width=0.8),
    MeshStyle(pattern="door_half_member", rgb=(0.78, 0.82, 0.92),
              alpha=0.45, layer=4),
    MeshStyle(pattern="fixed_frame", rgb=(0.86, 0.78, 0.74),
              alpha=0.55, layer=3, edges=True,
              edge_color=(0.40, 0.20, 0.10, 0.80), edge_width=0.8),
    MeshStyle(pattern="vehicle_body", rgb=(0.86, 0.78, 0.74),
              alpha=0.55, layer=3),
    # Pintle pin — bright accent so it reads as the axis.
    MeshStyle(pattern="pintle_pin", rgb=(0.65, 0.40, 0.30),
              alpha=1.0, layer=2, edge_width=0.7),
    MeshStyle(pattern="hinge_axis", rgb=(0.65, 0.40, 0.30),
              alpha=0.9, layer=2),
    # Hinge brackets + knuckles — opaque, slightly darker grey.
    MeshStyle(pattern="*hinge_bracket*", rgb=(0.74, 0.76, 0.80),
              alpha=1.0, layer=2),
    MeshStyle(pattern="*hinge_knuckle*", rgb=(0.70, 0.72, 0.76),
              alpha=1.0, layer=2),
    MeshStyle(pattern="*hinge_assembly*", rgb=(0.74, 0.76, 0.80),
              alpha=0.6, layer=2),
    MeshStyle(pattern="main_member", rgb=(0.74, 0.76, 0.80),
              alpha=1.0, layer=2),
    # Spring + link — gold accent.
    MeshStyle(pattern="spring_*", rgb=(0.90, 0.78, 0.40),
              alpha=1.0, layer=2),
    MeshStyle(pattern="u_shaped_link_member", rgb=(0.90, 0.78, 0.40),
              alpha=1.0, layer=2),
    MeshStyle(pattern="mounting_wall", rgb=(0.78, 0.74, 0.62),
              alpha=0.9, layer=2),
    # Fasteners — dark.
    MeshStyle(pattern="fastener_*", rgb=(0.30, 0.32, 0.34),
              alpha=1.0, layer=2, edge_width=0.4),
    # Marker / feature spheres — barely visible neutral grey, no edges.
    MeshStyle(pattern="*", rgb=(0.85, 0.85, 0.85),
              alpha=0.5, layer=1, edges=False),
]


def _style_for(label: str, table: list[MeshStyle]) -> MeshStyle:
    """Pick the FIRST matching style. Order matters — list specific
    patterns before catch-all globs."""
    for s in table:
        if fnmatch(label, s.pattern):
            return s
    return MeshStyle(pattern="*")


def _shade_face_colors(
    verts: np.ndarray,
    tris: np.ndarray,
    rgb: tuple[float, float, float],
    alpha: float,
) -> np.ndarray:
    """Per-triangle Lambert shade on the given base RGB + alpha."""
    a = verts[tris[:, 0]]
    b = verts[tris[:, 1]]
    c = verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    nn = np.linalg.norm(n, axis=1, keepdims=True)
    nn[nn < 1e-9] = 1.0
    n = n / nn
    light = np.array([0.4, 0.6, 0.7], dtype=np.float32)
    light /= np.linalg.norm(light)
    intensity = np.clip(0.55 + 0.40 * np.abs(n @ light), 0.55, 1.0)
    base = np.array(rgb, dtype=np.float32)
    cols = np.clip(base[None, :] * intensity[:, None], 0.0, 1.0)
    a_col = np.full((cols.shape[0], 1), float(alpha), dtype=np.float32)
    return np.concatenate([cols, a_col], axis=1)


def render_readable(
    *,
    step_path: Path,
    out_path: Path,
    elev: float = 0.0,
    azim: float = -90.0,
    resolution: int = 1280,
    tolerance: float = 0.4,
    styles: list[MeshStyle] | None = None,
    background: str = "white",
    show_labels: bool = False,
    margin_frac: float = 0.06,
) -> Path:
    """Render with per-component styling.

    Iterates through the imported compound's children, tessellates
    each separately, applies the matching MeshStyle. Opaque meshes
    are drawn first (lower layer), transparent ones last so they
    overlay the geometry behind them.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if styles is None:
        styles = US4807331A_DEMO_STYLES

    shape = bd.import_step(str(step_path))
    children = list(shape.children) if hasattr(shape, "children") else [shape]

    # Per-child draw records (sorted by layer ascending, so layer 1
    # paints first and layer 4 paints last on top).
    records: list[dict[str, Any]] = []
    label_anchors: list[tuple[str, np.ndarray]] = []
    overall_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    overall_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
    for child in children:
        label = getattr(child, "label", "") or ""
        style = _style_for(label, styles)
        try:
            verts, tris = _tessellate_shape(child, tolerance=tolerance)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tessellation failed for %s: %s", label, exc)
            continue
        if len(tris) == 0 or len(verts) == 0:
            continue
        # Camera basis for shading + edge selection.
        right, up, view = _camera_basis(elev, azim)
        R = np.stack([right, up, view], axis=0)
        a = verts[tris[:, 0]]
        b = verts[tris[:, 1]]
        c = verts[tris[:, 2]]
        fn_world = np.cross(b - a, c - a)
        nn = np.linalg.norm(fn_world, axis=1, keepdims=True)
        nn[nn < 1e-9] = 1.0
        fn_world = fn_world / nn
        fn_cam = fn_world @ R.T
        face_colors = _shade_face_colors(verts, tris, style.rgb, style.alpha)
        polys = verts[tris]
        edge_segments: list[np.ndarray] = []
        if style.edges:
            edges_idx = _feature_edges(tris, fn_cam)
            edge_segments = [
                np.stack([verts[i0], verts[i1]], axis=0).astype(np.float32)
                for (i0, i1) in edges_idx
            ]
        records.append({
            "label": label, "style": style,
            "polys": polys, "face_colors": face_colors,
            "edges": edge_segments,
        })
        # Bbox tracking
        v_min = verts.min(axis=0)
        v_max = verts.max(axis=0)
        overall_min = np.minimum(overall_min, v_min)
        overall_max = np.maximum(overall_max, v_max)
        # Label anchor at child centre (skip tiny markers).
        if (v_max - v_min).max() > 8.0:
            label_anchors.append((label, (v_min + v_max) / 2.0))

    if not records:
        raise RuntimeError("readable renderer: no drawable children")

    records.sort(key=lambda r: r["style"].layer)

    fig = plt.figure(figsize=(resolution / 100, resolution / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    for rec in records:
        pc = Poly3DCollection(
            rec["polys"],
            facecolors=rec["face_colors"],
            edgecolor="none",
            linewidth=0,
            antialiased=True,
        )
        pc.set_zsort("min")
        ax.add_collection3d(pc)
        if rec["edges"]:
            lc = Line3DCollection(
                [list(map(tuple, s)) for s in rec["edges"]],
                colors=rec["style"].edge_color,
                linewidths=rec["style"].edge_width,
            )
            ax.add_collection3d(lc)

    centre = (overall_min + overall_max) / 2.0
    half = float((overall_max - overall_min).max()) * (0.5 + margin_frac)
    ax.set_xlim(centre[0] - half, centre[0] + half)
    ax.set_ylim(centre[1] - half, centre[1] + half)
    ax.set_zlim(centre[2] - half, centre[2] + half)
    ax.set_box_aspect([1, 1, 1])
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.patch.set_facecolor(background)
    fig.tight_layout(pad=0)
    fig.savefig(out_path, dpi=100, bbox_inches="tight",
                pad_inches=0.05, facecolor=background)
    plt.close(fig)

    if show_labels and label_anchors:
        # Overlay labels in 2D after rendering. Project world
        # centres onto the image plane using the same camera basis.
        right, up, view = _camera_basis(elev, azim)
        img = Image.open(out_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 12)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        W, H = img.size
        for label, p in label_anchors:
            local = p - centre
            x = float(np.dot(local, right))
            y = float(np.dot(local, up))
            sx = (x / (2 * half) + 0.5) * W
            sy = (1.0 - (y / (2 * half) + 0.5)) * H
            draw.rectangle((sx - 2, sy - 2, sx + 2, sy + 2),
                           fill=(20, 20, 20))
            draw.text((sx + 5, sy - 7), label, fill=(20, 20, 20), font=font)
        img.save(out_path)

    return out_path


def render_exploded(
    *,
    step_path: Path,
    out_path: Path,
    elev: float = 18.0,
    azim: float = -65.0,
    resolution: int = 1280,
    explode_axis: str = "Y",
    explode_amount_mm: float = 60.0,
    styles: list[MeshStyle] | None = None,
) -> Path:
    """An exploded view by translating each layer further out
    along the depth axis. Opaque hinge parts stay; door + frame
    panels pull AWAY along ±Y so the hinge is fully visible.

    Implementation note: we apply the explode purely in the
    rendering layer (translate the polys, not the geometry) so
    the source STEP/GLB stays untouched.
    """
    if styles is None:
        styles = US4807331A_DEMO_STYLES

    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

    shape = bd.import_step(str(step_path))
    children = list(shape.children) if hasattr(shape, "children") else [shape]

    axis_idx = {"X": 0, "Y": 1, "Z": 2}[explode_axis]

    def _explode_offset(label: str) -> float:
        # Pull door panel one way, frame the other, hinges stay.
        if "door" in label:
            return -explode_amount_mm
        if "frame" in label or "vehicle" in label:
            return +explode_amount_mm
        return 0.0

    records: list[dict[str, Any]] = []
    overall_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    overall_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
    for child in children:
        label = getattr(child, "label", "") or ""
        style = _style_for(label, styles)
        try:
            verts, tris = _tessellate_shape(child, tolerance=0.4)
        except Exception:  # noqa: BLE001
            continue
        if len(tris) == 0:
            continue
        offset = _explode_offset(label)
        if abs(offset) > 1e-3:
            verts = verts.copy()
            verts[:, axis_idx] += offset
        right, up, view = _camera_basis(elev, azim)
        R = np.stack([right, up, view], axis=0)
        a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
        fn_world = np.cross(b - a, c - a)
        nn = np.linalg.norm(fn_world, axis=1, keepdims=True)
        nn[nn < 1e-9] = 1.0
        fn_world = fn_world / nn
        fn_cam = fn_world @ R.T
        face_colors = _shade_face_colors(verts, tris, style.rgb, style.alpha)
        polys = verts[tris]
        edge_segs: list[np.ndarray] = []
        if style.edges:
            edges_idx = _feature_edges(tris, fn_cam)
            edge_segs = [
                np.stack([verts[i0], verts[i1]], axis=0).astype(np.float32)
                for (i0, i1) in edges_idx
            ]
        records.append({"label": label, "style": style,
                        "polys": polys, "face_colors": face_colors,
                        "edges": edge_segs})
        overall_min = np.minimum(overall_min, verts.min(axis=0))
        overall_max = np.maximum(overall_max, verts.max(axis=0))

    records.sort(key=lambda r: r["style"].layer)
    fig = plt.figure(figsize=(resolution / 100, resolution / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    for rec in records:
        pc = Poly3DCollection(rec["polys"], facecolors=rec["face_colors"],
                              edgecolor="none", linewidth=0, antialiased=True)
        pc.set_zsort("min")
        ax.add_collection3d(pc)
        if rec["edges"]:
            lc = Line3DCollection(
                [list(map(tuple, s)) for s in rec["edges"]],
                colors=rec["style"].edge_color, linewidths=rec["style"].edge_width)
            ax.add_collection3d(lc)
    centre = (overall_min + overall_max) / 2.0
    half = float((overall_max - overall_min).max()) * 0.55
    ax.set_xlim(centre[0] - half, centre[0] + half)
    ax.set_ylim(centre[1] - half, centre[1] + half)
    ax.set_zlim(centre[2] - half, centre[2] + half)
    ax.set_box_aspect([1, 1, 1])
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=100, bbox_inches="tight",
                pad_inches=0.05, facecolor="white")
    plt.close(fig)
    return out_path


__all__ = [
    "MeshStyle",
    "US4807331A_DEMO_STYLES",
    "render_readable",
    "render_exploded",
]
