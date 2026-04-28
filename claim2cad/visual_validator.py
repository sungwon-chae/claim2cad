"""Visual validator: render CAD → compare to patent figure → score.

Pipeline:
  1. Tessellate a STEP/build123d shape into triangles.
  2. Render multiple views with matplotlib's 3D backend (no headless GL
     toolchain required — we paint shaded polygons in axes coords).
  3. Compose a side-by-side image: patent figure on the left, CAD render
     grid on the right.
  4. Send the composite image to a Claude-4.7 vision endpoint and ask for a
     structured similarity report.

The renderer is intentionally simple: solid-shaded triangles, white
background, three-point lighting via shading by face-normal · light-vec. It
will not pass for a Keyshot render, but it is sufficient to let the VLM
judge silhouette, proportion, and feature presence — which is what V11-4's
refinement loop actually needs.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from claim2cad.llm_vision import vision_completion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


# Default views: (name, elev_deg, azim_deg). Chosen so they show the same
# silhouettes a draftsman would draw: iso, front, right, top.
DEFAULT_VIEWS: tuple[tuple[str, float, float], ...] = (
    ("iso", 25.0, 45.0),
    ("front", 0.0, 0.0),
    ("right", 0.0, 90.0),
    ("top", 89.0, -90.0),
)


def _tessellate_shape(
    shape: bd.Shape | bd.Compound | bd.Part,
    tolerance: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices Nx3, triangle-indices Mx3) numpy arrays."""
    verts, tris = shape.tessellate(tolerance)
    v_arr = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=np.float32)
    t_arr = np.array(tris, dtype=np.int32)
    return v_arr, t_arr


def _shade_facecolors(
    verts: np.ndarray,
    tris: np.ndarray,
    base_color: tuple[float, float, float] = (0.78, 0.80, 0.84),
    lights: tuple[tuple[tuple[float, float, float], float], ...] = (
        ((0.4, 0.6, 0.8), 0.55),   # key light from upper-front-right
        ((-0.5, -0.3, 0.6), 0.30), # fill light from upper-back-left
        ((0.0, 0.0, -1.0), 0.15),  # bottom rim (slight)
    ),
    ambient: float = 0.55,
) -> np.ndarray:
    """Per-triangle Lambertian shading from a 3-light setup.

    Brighter ambient and softer directional contribution than the V11-2
    default — necessary because high-contrast shading on thin walls (a
    3mm U-bracket side) was reading as a separate object to the VLM.
    """
    a = verts[tris[:, 0]]
    b = verts[tris[:, 1]]
    c = verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    norms = np.linalg.norm(n, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    n = n / norms
    intensity = np.full(n.shape[0], ambient, dtype=np.float32)
    for direction, weight in lights:
        L = np.array(direction, dtype=np.float32)
        L /= np.linalg.norm(L) + 1e-9
        intensity = intensity + float(weight) * np.clip(np.abs(n @ L), 0.0, 1.0)
    intensity = np.clip(intensity, 0.0, 1.0)
    base = np.array(base_color, dtype=np.float32)
    cols = base[None, :] * intensity[:, None]
    cols = np.clip(cols, 0.0, 1.0)
    rgba = np.concatenate([cols, np.ones((cols.shape[0], 1), dtype=np.float32)], axis=1)
    return rgba


def render_shape_to_png(
    shape: bd.Shape | bd.Compound | bd.Part,
    out_path: Path | str,
    *,
    elev: float = 25.0,
    azim: float = 45.0,
    resolution: int = 1024,
    tolerance: float = 0.3,
    background: str = "white",
    edge_alpha: float = 0.0,
    edge_width: float = 0.0,
) -> Path:
    """Render a single view of a build123d shape to PNG.

    Defaults to no edge lines — wireframe-style edges over thin walls
    visually merge into "triangle" shapes that the VLM mis-reads. If you
    need wireframes for documentation, pass ``edge_alpha`` and
    ``edge_width`` > 0.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    verts, tris = _tessellate_shape(shape, tolerance=tolerance)
    if len(tris) == 0:
        raise RuntimeError("Tessellation produced 0 triangles — empty shape?")
    facecolors = _shade_facecolors(verts, tris)
    polys = verts[tris]

    bb_min = verts.min(axis=0)
    bb_max = verts.max(axis=0)
    center = (bb_min + bb_max) / 2.0
    span = float(np.max(bb_max - bb_min))
    half = span * 0.55  # slight margin

    fig = plt.figure(figsize=(resolution / 100, resolution / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    edgecolor = (0.0, 0.0, 0.0, edge_alpha) if edge_alpha > 0 else "none"
    pc = Poly3DCollection(
        polys,
        facecolors=facecolors,
        edgecolor=edgecolor,
        linewidth=edge_width,
        antialiased=True,
    )
    pc.set_zsort("min")  # stable depth ordering
    ax.add_collection3d(pc)
    ax.set_xlim(center[0] - half, center[0] + half)
    ax.set_ylim(center[1] - half, center[1] + half)
    ax.set_zlim(center[2] - half, center[2] + half)
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:  # noqa: BLE001 — older mpl
        pass
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_facecolor(background)
    fig.patch.set_facecolor(background)

    fig.savefig(out_path, dpi=100, bbox_inches="tight", pad_inches=0.05, facecolor=background)
    plt.close(fig)
    return out_path


def render_step_to_pngs(
    step_path: Path | str,
    out_dir: Path | str,
    *,
    views: tuple[tuple[str, float, float], ...] = DEFAULT_VIEWS,
    resolution: int = 1024,
    tolerance: float = 0.3,
    edge_alpha: float = 0.10,
    edge_width: float = 0.10,
) -> list[Path]:
    """Render multiple views of a STEP file. Returns the list of PNG paths."""
    step_path = Path(step_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shape = bd.import_step(str(step_path))
    out_paths: list[Path] = []
    for name, elev, azim in views:
        png = out_dir / f"{step_path.stem}_{name}.png"
        render_shape_to_png(
            shape,
            png,
            elev=elev,
            azim=azim,
            resolution=resolution,
            tolerance=tolerance,
            edge_alpha=edge_alpha,
            edge_width=edge_width,
        )
        out_paths.append(png)
    return out_paths


def render_glb_to_png(
    glb_path: Path | str,
    view_angles: list[tuple[str, float, float]] | None = None,
    out_dir: Path | str | None = None,
    *,
    resolution: int = 1024,
) -> list[Path]:
    """Convenience wrapper kept for the design-doc API. Internally we render
    from the sibling STEP file (same directory, same stem) since GLB requires
    a tessellated round-trip we'd rather avoid."""
    glb_path = Path(glb_path)
    step_path = glb_path.with_suffix(".step")
    if not step_path.exists():
        raise FileNotFoundError(
            f"Expected STEP sibling at {step_path}; render_glb_to_png needs it."
        )
    out_dir = Path(out_dir) if out_dir is not None else glb_path.parent / "renders"
    views = tuple(view_angles) if view_angles else DEFAULT_VIEWS
    return render_step_to_pngs(step_path, out_dir, views=views, resolution=resolution)


# ---------------------------------------------------------------------------
# Composite "side-by-side" image
# ---------------------------------------------------------------------------


def make_comparison_grid(
    rendered_pngs: list[Path],
    figure_png: Path,
    out_path: Path,
    *,
    label_left: str = "Patent figure",
    label_right: str = "v1.1 CAD",
    cell_px: int = 512,
) -> Path:
    """Compose patent figure on the left, 2x2 (or wider) render grid on the
    right. Saves as PNG. The composite is intentionally compact: this is
    what gets sent to the VLM, so smaller = cheaper input tokens."""
    figure = Image.open(figure_png).convert("RGB")
    # Resize figure into a (cell_px*2) tall block.
    fig_w_target = cell_px * 2
    fig_h_target = cell_px * 2
    figure_resized = _fit_into_box(figure, fig_w_target, fig_h_target, bg=(255, 255, 255))

    rendered_imgs = [_fit_into_box(Image.open(p).convert("RGB"), cell_px, cell_px, bg=(255, 255, 255)) for p in rendered_pngs]
    # Pad to a multiple of 2x2; put placeholders for missing tiles.
    while len(rendered_imgs) < 4:
        blank = Image.new("RGB", (cell_px, cell_px), (240, 240, 240))
        rendered_imgs.append(blank)
    rows = (len(rendered_imgs) + 1) // 2
    grid_w = cell_px * 2
    grid_h = cell_px * rows
    grid = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))
    for i, im in enumerate(rendered_imgs):
        gx = (i % 2) * cell_px
        gy = (i // 2) * cell_px
        grid.paste(im, (gx, gy))

    pad = 24
    label_h = 32
    composite_w = figure_resized.width + grid.width + pad * 3
    composite_h = max(figure_resized.height, grid.height) + pad * 2 + label_h
    composite = Image.new("RGB", (composite_w, composite_h), (255, 255, 255))
    composite.paste(figure_resized, (pad, pad + label_h))
    composite.paste(grid, (pad * 2 + figure_resized.width, pad + label_h))

    draw = ImageDraw.Draw(composite)
    try:
        font = ImageFont.truetype("Helvetica", 22)
    except OSError:
        font = ImageFont.load_default()
    draw.text((pad, pad), label_left, fill=(20, 20, 20), font=font)
    draw.text((pad * 2 + figure_resized.width, pad), label_right, fill=(20, 20, 20), font=font)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(out_path)
    return out_path


def _fit_into_box(img: Image.Image, w: int, h: int, bg: tuple[int, int, int]) -> Image.Image:
    """Letterbox an image into a w×h box with background ``bg``."""
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), bg)
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


# ---------------------------------------------------------------------------
# Similarity scoring via VLM
# ---------------------------------------------------------------------------


@dataclass
class SimilarityReport:
    """Structured similarity-to-figure report."""

    overall_score: float = 0.0
    silhouette_score: float = 0.0
    proportion_score: float = 0.0
    feature_score: float = 0.0
    arrangement_score: float = 0.0
    defects: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        d["raw"] = self.raw
        return d


_SYSTEM_PROMPT = (
    "You are a senior mechanical engineer reviewing CAD output for visual "
    "fidelity to a patent drawing. Be honest. The CAD model is allowed to be "
    "stylised (matte shading, simplified teeth) but it should match the "
    "drawing on silhouette, proportion, feature presence (holes, fillets, "
    "ends), and arrangement of components. Score on a 0-10 integer scale "
    "(10 = visually indistinguishable in topology and proportion; 5 = "
    "recognisable but obviously approximate; 0 = unrelated). Always return "
    "valid JSON."
)

_USER_TEMPLATE = """The image you are looking at is a side-by-side composite:
* LEFT — the patent drawing ({figure_label}).
* RIGHT — a 2x2 grid of multi-view renders of the candidate CAD model.

Patent context: {patent_context}

Components the CAD model is supposed to depict (from claim IR):
{component_list}

Return JSON with this exact shape (no extra keys):
{{
  "overall_score": <int 0-10>,
  "silhouette_score": <int 0-10>,
  "proportion_score": <int 0-10>,
  "feature_score": <int 0-10>,
  "arrangement_score": <int 0-10>,
  "defects": [
    {{"component": "<component_id or null>", "issue": "<short>", "severity": "minor|moderate|major"}}
  ],
  "notes": "<1-2 sentences on what is right and what is wrong>"
}}
"""


def compare_to_figure(
    rendered_pngs: list[Path],
    figure_png: Path,
    *,
    composite_path: Path | None = None,
    patent_context: str = "",
    component_list: list[str] | None = None,
    figure_label: str = "figure_1",
    task_type: str = "v11_visual_validation",
    dry_run: bool = False,
) -> SimilarityReport:
    """Score how close ``rendered_pngs`` look to ``figure_png``.

    ``dry_run=True`` skips the VLM call and returns a stub report — used by
    CI / offline tests to exercise the pipeline without spending tokens.
    """
    if composite_path is None:
        composite_path = figure_png.parent / "_validation_composite.png"
    composite = make_comparison_grid(rendered_pngs, figure_png, composite_path)

    if dry_run:
        logger.info("compare_to_figure dry-run: returning stub report")
        return SimilarityReport(
            overall_score=0.0,
            silhouette_score=0.0,
            proportion_score=0.0,
            feature_score=0.0,
            arrangement_score=0.0,
            defects=[{"component": None, "issue": "dry_run — no VLM call made", "severity": "minor"}],
            notes="dry-run stub",
            raw={"dry_run": True, "composite_path": str(composite)},
        )

    component_lines = "\n".join(f"  - {c}" for c in (component_list or [])) or "  (none provided)"
    user_prompt = _USER_TEMPLATE.format(
        figure_label=figure_label,
        patent_context=patent_context or "(none provided)",
        component_list=component_lines,
    )
    raw = vision_completion(
        image_path=composite,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        task_type=task_type,
    )
    report = _parse_report(raw)
    report.raw = raw
    return report


def _parse_report(raw: dict[str, Any]) -> SimilarityReport:
    def _score(key: str) -> float:
        v = raw.get(key, 0)
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    defects = raw.get("defects") or []
    if not isinstance(defects, list):
        defects = []
    return SimilarityReport(
        overall_score=_score("overall_score"),
        silhouette_score=_score("silhouette_score"),
        proportion_score=_score("proportion_score"),
        feature_score=_score("feature_score"),
        arrangement_score=_score("arrangement_score"),
        defects=[d for d in defects if isinstance(d, dict)],
        notes=str(raw.get("notes", "")),
    )


# ---------------------------------------------------------------------------
# CLI: validate a v1.0 example end-to-end
# ---------------------------------------------------------------------------


def _component_list_from_ir(ir_path: Path) -> list[str]:
    if not ir_path.exists():
        return []
    try:
        ir = json.loads(ir_path.read_text("utf-8"))
    except json.JSONDecodeError:
        return []
    return [c.get("id", "?") + ": " + c.get("label", "") for c in ir.get("components", [])]


def validate_example(
    example_dir: Path | str,
    *,
    step_filename: str = "model.step",
    figure_filename: str = "figures/figure_1.png",
    out_filename: str = "baseline_validation.json",
    dry_run: bool = False,
    patent_context: str = "",
) -> dict[str, Any]:
    """Render the example's STEP, score it against the primary figure, and
    save the report. Returns the report dict."""
    example_dir = Path(example_dir)
    step_path = example_dir / step_filename
    figure_path = example_dir / figure_filename
    if not step_path.exists():
        raise FileNotFoundError(f"STEP not found: {step_path}")
    if not figure_path.exists():
        raise FileNotFoundError(f"Figure not found: {figure_path}")
    renders_dir = example_dir / "renders_v1.0"
    renders = render_step_to_pngs(step_path, renders_dir)
    components = _component_list_from_ir(example_dir / "claim_ir.json")
    composite = example_dir / "render_v1.0_vs_figure.png"
    report = compare_to_figure(
        renders,
        figure_path,
        composite_path=composite,
        patent_context=patent_context,
        component_list=components,
        figure_label=figure_path.name,
        dry_run=dry_run,
    )
    out_path = example_dir / out_filename
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    logger.info("Saved baseline validation report to %s", out_path)
    return report.to_dict()


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render a STEP, compare to a patent figure, score it.")
    p.add_argument("example_dir", type=Path, help="Path to an examples/<name> directory.")
    p.add_argument("--step", default="model.step")
    p.add_argument("--figure", default="figures/figure_1.png")
    p.add_argument("--out", default="baseline_validation.json")
    p.add_argument("--dry-run", action="store_true", help="Skip VLM call.")
    p.add_argument(
        "--patent-context",
        default="",
        help="Short description of the patent (passed to the VLM prompt).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CLAIM2CAD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)-22s :: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    args = _build_argparser().parse_args(argv)
    report = validate_example(
        args.example_dir,
        step_filename=args.step,
        figure_filename=args.figure,
        out_filename=args.out,
        dry_run=args.dry_run,
        patent_context=args.patent_context,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
