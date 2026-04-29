"""V14-B — image-heuristic figure view classifier.

Detects the view_type of a patent figure WITHOUT an LLM call.
Three signals on a binarized version of the inked region:

  1. Aspect ratio of the inked bounding box.
  2. Dominant line orientation (vertical vs horizontal opens).
  3. Number of distinct ink CONNECTED COMPONENTS — proxy for
     "multiple separate drawings on the same sheet".

Output schema (figure_views_v14.json):

  view_type      one of: top | front | side | sectional | oblique |
                 isometric | exploded | multi_view_sheet | schematic |
                 unknown
  primary_view   the view we should reconstruct from
  secondary_views[]
  required_camera   "top" | "front" | "right" | "iso" | "patent_oblique"
  view_regions[]    pixel bboxes per detected subview (multi-view only)
  evidence[]        one-line explanations per signal
  confidence        0..1
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ViewRegion:
    bbox: list[int]
    view_type: str = "unknown"
    label: str = ""


@dataclass
class FigureViews:
    example_id: str
    figure_path: str
    view_type: str = "unknown"
    primary_view: str = "unknown"
    secondary_views: list[str] = field(default_factory=list)
    required_camera: str = "iso"
    view_regions: list[ViewRegion] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VIEW_CAMERA = {
    "top": "top",
    "front": "front",
    "side": "right",
    "sectional": "front",
    "oblique": "patent_oblique",
    "isometric": "iso",
    "exploded": "iso",
    "multi_view_sheet": "patent_oblique",
    "schematic": "front",
    "unknown": "iso",
}


def _binarize(img):
    import numpy as np
    arr = np.array(img.convert("L"))
    mean = arr.mean()
    th = max(220, mean - 8)
    return (arr < th).astype("uint8")


def _bbox(mask):
    import numpy as np
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        h, w = mask.shape
        return (0, 0, w, h)
    return (int(xs.min()), int(ys.min()),
            int(xs.max()), int(ys.max()))


def _connected_components(mask, *, min_area_frac: float = 0.005):
    """Pixel-area filtered CC pass. min_area_frac is the minimum
    fraction of TOTAL IMAGE pixels a component must occupy to
    count as a 'subview' — protects against the classifier
    treating callout numbers as separate drawings."""
    import numpy as np
    try:
        from scipy import ndimage
        h, w = mask.shape
        # Aggressive dilation: a 13x13 kernel x 8 iterations welds
        # callout digits onto the nearest drawing while keeping
        # truly separated drawings apart.
        kernel = np.ones((11, 11), dtype="uint8")
        dilated = ndimage.binary_dilation(
            mask, structure=kernel, iterations=4).astype("uint8")
        labels, n = ndimage.label(dilated)
        boxes = []
        min_area = int(h * w * min_area_frac)
        for i in range(1, n + 1):
            ys, xs = np.where(labels == i)
            if len(xs) < min_area:
                continue
            boxes.append((int(xs.min()), int(ys.min()),
                          int(xs.max()), int(ys.max())))
        return boxes
    except Exception:
        # Coarse grid fallback
        h, w = mask.shape
        cells = []
        for iy in range(4):
            for ix in range(4):
                y0, y1 = (h * iy) // 4, (h * (iy + 1)) // 4
                x0, x1 = (w * ix) // 4, (w * (ix + 1)) // 4
                if mask[y0:y1, x0:x1].sum() > 1500:
                    cells.append((x0, y0, x1, y1))
        return cells


def _line_orientation(mask):
    try:
        import numpy as np
        from scipy import ndimage
        v_open = ndimage.binary_opening(
            mask, structure=np.ones((9, 1), dtype="uint8"))
        h_open = ndimage.binary_opening(
            mask, structure=np.ones((1, 9), dtype="uint8"))
        total = max(int(mask.sum()), 1)
        return (float(v_open.sum()) / total,
                float(h_open.sum()) / total)
    except Exception:
        return (0.0, 0.0)


def _hatching_density(mask, regions):
    """Sectional drawings have dense diagonal hatching → higher
    average ink density inside the region."""
    densities = []
    for x0, y0, x1, y1 in regions:
        sub = mask[y0:y1, x0:x1]
        if sub.size == 0:
            continue
        densities.append(float(sub.mean()))
    if not densities:
        return 0.0
    return max(densities)


def classify_figure(figure_path: Path,
                      example_id: str = "") -> FigureViews:
    rep = FigureViews(example_id=example_id,
                       figure_path=str(figure_path))
    try:
        from PIL import Image
        img = Image.open(figure_path)
    except Exception as exc:  # noqa: BLE001
        rep.notes = f"PIL load failed: {exc}"
        return rep

    try:
        mask = _binarize(img)
    except Exception as exc:  # noqa: BLE001
        rep.notes = f"binarize failed: {exc}"
        return rep

    bbox = _bbox(mask)
    bw = max(bbox[2] - bbox[0], 1)
    bh = max(bbox[3] - bbox[1], 1)
    aspect = bw / bh
    rep.evidence.append(f"aspect={aspect:.3f}")

    cc_boxes = _connected_components(mask)
    rep.evidence.append(f"connected_components={len(cc_boxes)}")

    v_frac, h_frac = _line_orientation(mask)
    rep.evidence.append(
        f"vert_frac={v_frac:.3f} horiz_frac={h_frac:.3f}")

    max_density = _hatching_density(mask, cc_boxes)
    rep.evidence.append(f"max_region_density={max_density:.3f}")

    # Multi-view sheet: ≥2 sizable separated drawings.
    n_big = sum(1 for (x0, y0, x1, y1) in cc_boxes
                 if (x1 - x0) > bw * 0.18 and (y1 - y0) > bh * 0.10)
    if n_big >= 2:
        rep.view_type = "multi_view_sheet"
        regions = [
            ViewRegion(bbox=list(b),
                         view_type="unknown",
                         label=f"subview_{i + 1}")
            for i, b in enumerate(cc_boxes)
        ]
        labelled = []
        for vr in regions:
            x0, y0, x1, y1 = vr.bbox
            sub = mask[y0:y1, x0:x1]
            sub_aspect = (x1 - x0) / max(y1 - y0, 1)
            sub_dense = float(sub.mean()) if sub.size else 0.0
            if sub_dense > 0.16:
                vr.view_type = "sectional"
            elif 0.85 <= sub_aspect <= 1.18:
                vr.view_type = "plan"
            elif sub_aspect > 1.4:
                vr.view_type = "top"
            elif sub_aspect < 0.75:
                vr.view_type = "front"
            else:
                vr.view_type = "oblique"
            labelled.append(vr.view_type)
        regions.sort(
            key=lambda r: (r.bbox[2] - r.bbox[0]) *
                          (r.bbox[3] - r.bbox[1]),
            reverse=True)
        rep.view_regions = regions
        rep.primary_view = regions[0].view_type
        rep.secondary_views = [r.view_type for r in regions[1:]]
        rep.required_camera = "patent_oblique"
        rep.confidence = 0.75
        rep.evidence.append(f"subviews={labelled}")
        return rep

    # Sectional whole-image — needs BOTH high density AND a wide
    # aspect (sectional cuts of mechanisms are typically wider
    # than tall). The earlier 0.16 threshold over-fired on
    # oblique drawings whose label leader-line bundles raised the
    # density.
    if max_density > 0.22 and aspect > 1.2:
        rep.view_type = "sectional"
        rep.primary_view = "sectional"
        rep.required_camera = "front"
        rep.confidence = 0.65
        return rep

    # Single-view aspect classification.
    if aspect > 1.6:
        rep.view_type = "top" if aspect > 1.9 else "side"
    elif aspect < 0.65:
        rep.view_type = "front"
    else:
        rep.view_type = "oblique"
    rep.primary_view = rep.view_type
    rep.required_camera = VIEW_CAMERA[rep.view_type]
    rep.confidence = 0.55
    return rep


def classify_example(example_dir: Path) -> FigureViews:
    fig_path = example_dir / "figures" / "figure_1.png"
    return classify_figure(fig_path, example_id=example_dir.name)


def save_views(rep: FigureViews, example_dir: Path) -> Path:
    p = example_dir / "figure_views_v14.json"
    p.write_text(json.dumps(rep.to_dict(), indent=2) + "\n",
                  encoding="utf-8")
    return p


def render_view_debug(rep: FigureViews,
                        example_dir: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw
        img = Image.open(rep.figure_path).convert("RGB")
        d = ImageDraw.Draw(img)
        for i, vr in enumerate(rep.view_regions):
            x0, y0, x1, y1 = vr.bbox
            color = [(220, 30, 30), (30, 130, 200),
                      (230, 160, 30), (40, 160, 80),
                      (160, 60, 200)][i % 5]
            d.rectangle([(x0, y0), (x1, y1)], outline=color, width=4)
            d.text((x0 + 6, y0 + 6),
                     f"{vr.label} {vr.view_type}", fill=color)
        d.rectangle([(0, 0), (img.width, 32)], fill=(20, 20, 20))
        d.text((10, 8),
                 f"view={rep.view_type} cam={rep.required_camera} "
                 f"conf={rep.confidence:.2f}",
                 fill=(255, 255, 255))
        out = example_dir / "renders_v1.4" / "view_region_debug.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return out
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--all-real-patents", action="store_true")
    p.add_argument("--example", action="append", default=[])
    p.add_argument("--real-patents-dir", type=Path,
                    default=Path("examples/real_patents"))
    args = p.parse_args(argv)
    only = set(args.example) if args.example else None
    out = []
    for ex in sorted(args.real_patents_dir.iterdir()):
        if not ex.is_dir():
            continue
        if only and ex.name not in only:
            continue
        rep = classify_example(ex)
        save_views(rep, ex)
        render_view_debug(rep, ex)
        out.append({"id": ex.name,
                     "view_type": rep.view_type,
                     "primary": rep.primary_view,
                     "secondary": rep.secondary_views,
                     "camera": rep.required_camera,
                     "n_regions": len(rep.view_regions)})
        print(f"{ex.name}: {rep.view_type} "
              f"({rep.required_camera}) conf={rep.confidence:.2f}")
    Path("examples/reports").mkdir(exist_ok=True)
    Path("examples/reports/V14_FIGURE_VIEWS.json").write_text(
        json.dumps({"examples": out}, indent=2) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
