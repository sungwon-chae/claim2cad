"""V12-G — human-aligned evaluation.

The V11 metrics were almost all data-derived: claim spans verified,
GLB nodes present, callout coverage, projection anchor distance.
Those scores were green while the actual render still looked like
a heap of bars. V12 adds metrics that **inspect the render** and
**penalise central piles** so the composite refuses credit for a
visually wrong assembly.

Five new axes — every one looks at the rendered image or the CAD
geometry, not at the JSON labels:

  1. figure_resemblance_score — silhouette IoU between
     ``solid_figure_aligned.png`` (or readable_figure_aligned) and
     ``figure_1.png`` after both are reduced to binary
     foreground masks at the same scale.
  2. panel_dominance_score — what fraction of the rendered image
     is covered by the door_panel + fixed_frame meshes vs the
     hinge cluster + small parts. A "central pile" has tiny panel
     coverage; a real assembly has the panels as the dominant
     shapes.
  3. hinge_axis_visibility_score — does the pintle pin appear as
     a long-thin shape in the render? Measured by tessellating
     the pintle_pin child and projecting it; pass if its
     screen-space aspect ratio is > 4:1.
  4. floating_component_count — how many CAD children have NO
     intersection with any other child's bounding box (excluding
     small markers). A high count means components are floating
     in space rather than attached.
  5. demo_readability_score — composite "is this convincing?"
     score derived from (1)-(4) plus a hard fail if there are
     fewer than 5 distinct large meshes (a "central pile" gets
     a 0).

The new eval composite gives V12 axes 50% of the weight. The V11
axes (span, GLB coverage, etc.) keep the other 50% so structural
correctness still matters.
"""
from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class V12EvalReport:
    example_id: str
    example_dir: str
    figure_resemblance: dict[str, Any] = field(default_factory=dict)
    panel_dominance: dict[str, Any] = field(default_factory=dict)
    hinge_axis_visibility: dict[str, Any] = field(default_factory=dict)
    floating_components: dict[str, Any] = field(default_factory=dict)
    demo_readability: dict[str, Any] = field(default_factory=dict)
    v11_carryover: dict[str, Any] = field(default_factory=dict)
    overall: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "example_dir": self.example_dir,
            "figure_resemblance": self.figure_resemblance,
            "panel_dominance": self.panel_dominance,
            "hinge_axis_visibility": self.hinge_axis_visibility,
            "floating_components": self.floating_components,
            "demo_readability": self.demo_readability,
            "v11_carryover": self.v11_carryover,
            "overall": self.overall,
            "notes": self.notes,
        }


def _read_image_mask(
    path: Path,
    *,
    threshold: int = 220,
) -> tuple[Any, tuple[int, int]]:
    from PIL import Image
    import numpy as np

    img = np.asarray(Image.open(path).convert("L"))
    mask = img < threshold
    return mask, (img.shape[1], img.shape[0])  # (w, h)


def _eval_figure_resemblance(example_dir: Path) -> dict[str, Any]:
    """Silhouette IoU between figure_1 and the figure-aligned render.

    Both images are converted to binary foreground masks
    (non-white pixels). Each mask is centred + scaled so its
    bounding box exactly fills a fixed canvas, then compared.

    Score = (intersection / union) of the two masks.
    """
    figure_path = example_dir / "figures" / "figure_1.png"
    candidates = [
        example_dir / "renders_v1.2" / "readable_figure_aligned.png",
        example_dir / "renders_v1.2" / "solid_figure_aligned.png",
        example_dir / "renders_v1.1" / "figure_aligned_view.png",
    ]
    cad_path = next((c for c in candidates if c.exists()), None)
    if not figure_path.exists() or cad_path is None:
        return {"score": 0.0, "note": "no figure or CAD render"}
    try:
        from PIL import Image
        import numpy as np

        f_mask, _ = _read_image_mask(figure_path, threshold=220)
        c_mask, _ = _read_image_mask(cad_path, threshold=220)

        def _crop_to_fg(m):
            ys, xs = np.where(m)
            if len(xs) == 0:
                return m
            return m[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]

        f = _crop_to_fg(f_mask)
        c = _crop_to_fg(c_mask)
        if f.size == 0 or c.size == 0:
            return {"score": 0.0, "note": "empty mask"}
        # Normalise both to a 256x256 canvas with letterboxing.
        target = 256

        def _scale_to_canvas(m):
            from PIL import Image as PI
            h, w = m.shape
            ratio = min(target / w, target / h)
            new_w = max(1, int(w * ratio))
            new_h = max(1, int(h * ratio))
            mp = PI.fromarray((m.astype("uint8") * 255))
            mp = mp.resize((new_w, new_h), PI.LANCZOS)
            arr = np.asarray(mp) > 127
            canvas = np.zeros((target, target), dtype=bool)
            ox = (target - new_w) // 2
            oy = (target - new_h) // 2
            canvas[oy: oy + new_h, ox: ox + new_w] = arr
            return canvas

        f_c = _scale_to_canvas(f)
        c_c = _scale_to_canvas(c)
        intersection = np.logical_and(f_c, c_c).sum()
        union = np.logical_or(f_c, c_c).sum()
        iou = float(intersection) / max(int(union), 1)
        return {
            "score": round(iou, 3),
            "rendered_path": str(cad_path.relative_to(example_dir)),
            "intersection_pixels": int(intersection),
            "union_pixels": int(union),
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_panel_dominance(example_dir: Path) -> dict[str, Any]:
    """In the figure-aligned render, what fraction of the foreground
    pixels come from the door_panel + fixed_frame meshes?

    We can't trivially split the existing render by mesh, so we
    re-render JUST those meshes and compare their foreground area
    to the full assembly's foreground area.

    A "central pile" with tiny panels has score < 0.30. A panel-
    dominated assembly scores > 0.50.
    """
    step_path = example_dir / "model_v1.2.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no model_v1.2.step"}
    try:
        import build123d as bd
        import numpy as np
        import tempfile
        from PIL import Image
        from claim2cad.visual_validator import render_step_to_solid

        shape = bd.import_step(str(step_path))
        if not hasattr(shape, "children") or not shape.children:
            return {"score": 0.0, "note": "compound has no children"}
        # Identify panel children.
        panel_labels = {"door_panel", "fixed_frame",
                        "door_half_member", "vehicle_body"}
        panel_children = [c for c in shape.children
                           if c.label in panel_labels]
        if not panel_children:
            return {"score": 0.0, "note": "no panel children present"}
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            # Render full assembly silhouette.
            full_img = tdir / "full.png"
            render_step_to_solid(step_path, full_img,
                                  elev=0.0, azim=-90.0,
                                  resolution=600)
            full_mask = np.asarray(Image.open(full_img).convert("L")) < 220

            # Render only the panel meshes.
            panel_compound = bd.Compound(label="panels", children=panel_children)
            panel_step = tdir / "panels.step"
            bd.export_step(panel_compound, str(panel_step))
            panel_img = tdir / "panels.png"
            render_step_to_solid(panel_step, panel_img,
                                  elev=0.0, azim=-90.0,
                                  resolution=600)
            panel_mask = np.asarray(Image.open(panel_img).convert("L")) < 220

            full_pixels = int(full_mask.sum())
            panel_pixels = int(panel_mask.sum())
            if full_pixels == 0:
                return {"score": 0.0, "note": "empty full silhouette"}
            ratio = float(panel_pixels) / max(full_pixels, 1)
            # Score: 0 at ratio<=0.10 (no panels), 1 at ratio>=0.50.
            score = max(0.0, min(1.0, (ratio - 0.10) / 0.40))
            return {
                "score": round(score, 3),
                "panel_pixel_ratio": round(ratio, 3),
                "panel_children": [c.label for c in panel_children],
                "full_pixels": full_pixels,
                "panel_pixels": panel_pixels,
            }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_hinge_axis_visibility(example_dir: Path) -> dict[str, Any]:
    """Does the pintle pin / hinge axis appear as a long-thin
    feature in the render? Measured from CAD geometry directly."""
    step_path = example_dir / "model_v1.2.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no model_v1.2.step"}
    try:
        import build123d as bd

        shape = bd.import_step(str(step_path))
        target_labels = {"pintle_pin", "hinge_axis"}
        for c in getattr(shape, "children", []):
            if c.label in target_labels and c.label == "pintle_pin":
                bb = c.bounding_box()
                sx = bb.max.X - bb.min.X
                sy = bb.max.Y - bb.min.Y
                sz = bb.max.Z - bb.min.Z
                long_axis = max(sx, sy, sz)
                short_axis = max(min(sx, sy, sz), 0.1)
                aspect = long_axis / short_axis
                # Score: 0 at aspect<3 (cube-like), 1 at aspect>=10.
                score = max(0.0, min(1.0, (aspect - 3.0) / 7.0))
                return {
                    "score": round(score, 3),
                    "long_axis_mm": round(long_axis, 1),
                    "short_axis_mm": round(short_axis, 1),
                    "aspect_ratio": round(aspect, 2),
                }
        return {"score": 0.0, "note": "no pintle_pin child"}
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_floating_components(example_dir: Path) -> dict[str, Any]:
    """How many CAD children have NO intersection with any other
    child's bounding box? Markers and tiny features (< 4 mm in any
    dimension) are excluded — they're meant to be attached.
    """
    step_path = example_dir / "model_v1.2.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no model_v1.2.step"}
    try:
        import build123d as bd

        shape = bd.import_step(str(step_path))
        children = list(getattr(shape, "children", [])) or [shape]
        bboxes: list[tuple[str, tuple[float, float, float, float, float, float]]] = []
        for c in children:
            try:
                bb = c.bounding_box()
            except Exception:  # noqa: BLE001
                continue
            sx = bb.max.X - bb.min.X
            sy = bb.max.Y - bb.min.Y
            sz = bb.max.Z - bb.min.Z
            if max(sx, sy, sz) < 4.0:
                continue  # marker — exclude from this metric
            bboxes.append((c.label or "", (
                bb.min.X, bb.min.Y, bb.min.Z,
                bb.max.X, bb.max.Y, bb.max.Z,
            )))
        floating: list[str] = []
        for i, (li, bi) in enumerate(bboxes):
            intersects = False
            for j, (_, bj) in enumerate(bboxes):
                if i == j:
                    continue
                if (bi[0] <= bj[3] and bi[3] >= bj[0]
                        and bi[1] <= bj[4] and bi[4] >= bj[1]
                        and bi[2] <= bj[5] and bi[5] >= bj[2]):
                    intersects = True
                    break
            if not intersects:
                floating.append(li)
        n_total = len(bboxes)
        n_float = len(floating)
        # Score: 1 when floating == 0, decays linearly to 0 at
        # floating == 30 % of total.
        score = 1.0 - min(1.0, n_float / max(n_total * 0.30, 1.0))
        return {
            "score": round(score, 3),
            "n_total": n_total,
            "n_floating": n_float,
            "floating_examples": floating[:6],
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_demo_readability(
    figure_resemblance: float,
    panel_dominance: float,
    hinge_axis_visibility: float,
    floating_score: float,
    n_distinct_large: int,
) -> dict[str, Any]:
    """Composite "is this convincing?" score.

    A central pile is detected by:
      - panel_dominance < 0.20
      - n_distinct_large < 5
      - floating_score < 0.5
    If any TWO of these hold, the score is 0 (refuse credit).
    """
    central_pile_signals = sum([
        1 if panel_dominance < 0.20 else 0,
        1 if n_distinct_large < 5 else 0,
        1 if floating_score < 0.50 else 0,
    ])
    if central_pile_signals >= 2:
        return {
            "score": 0.0,
            "verdict": "central pile — refusing credit",
            "panel_dominance": panel_dominance,
            "n_distinct_large": n_distinct_large,
            "floating_score": floating_score,
        }
    raw = (
        0.30 * figure_resemblance
        + 0.30 * panel_dominance
        + 0.20 * hinge_axis_visibility
        + 0.20 * floating_score
    )
    return {
        "score": round(raw, 3),
        "verdict": "ok" if raw > 0.50 else "weak",
        "panel_dominance": panel_dominance,
        "n_distinct_large": n_distinct_large,
        "floating_score": floating_score,
    }


def _v11_carryover(example_dir: Path) -> dict[str, Any]:
    """Run the V11 evaluator and pass through its overall composite
    so the V12 report shows both lenses at once."""
    try:
        from claim2cad.eval_v11 import evaluate_example as _eval_v11

        rep = _eval_v11(example_dir)
        return {
            "v11_composite": rep.overall.get("composite", 0.0),
            "axis_scores": {
                k: getattr(rep, k).get("score", 0.0) for k in (
                    "span_correctness", "glb_coverage",
                    "figure_callout_coverage", "geometric_invariants",
                    "projection_fit", "assembly_coherence",
                    "projection_anchor_match", "central_density",
                    "view_match", "hotspot_grounding",
                )
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"v11_composite": 0.0, "error": str(exc)}


def _count_distinct_large_meshes(example_dir: Path) -> int:
    step_path = example_dir / "model_v1.2.step"
    if not step_path.exists():
        return 0
    try:
        import build123d as bd

        shape = bd.import_step(str(step_path))
        n = 0
        for c in getattr(shape, "children", []):
            try:
                bb = c.bounding_box()
            except Exception:  # noqa: BLE001
                continue
            if max(bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z) >= 8.0:
                n += 1
        return n
    except Exception:  # noqa: BLE001
        return 0


def evaluate_example_v12(example_dir: Path) -> V12EvalReport:
    example_dir = example_dir.resolve()
    rep = V12EvalReport(
        example_id=example_dir.name, example_dir=str(example_dir),
    )
    rep.figure_resemblance = _eval_figure_resemblance(example_dir)
    rep.panel_dominance = _eval_panel_dominance(example_dir)
    rep.hinge_axis_visibility = _eval_hinge_axis_visibility(example_dir)
    rep.floating_components = _eval_floating_components(example_dir)
    n_large = _count_distinct_large_meshes(example_dir)
    rep.demo_readability = _eval_demo_readability(
        figure_resemblance=float(rep.figure_resemblance.get("score", 0.0)),
        panel_dominance=float(rep.panel_dominance.get("score", 0.0)),
        hinge_axis_visibility=float(rep.hinge_axis_visibility.get("score", 0.0)),
        floating_score=float(rep.floating_components.get("score", 0.0)),
        n_distinct_large=n_large,
    )
    rep.v11_carryover = _v11_carryover(example_dir)

    weights = {
        "figure_resemblance": 0.15,
        "panel_dominance": 0.15,
        "hinge_axis_visibility": 0.10,
        "floating_components": 0.10,
        "demo_readability": 0.20,
        "v11": 0.30,
    }
    composite = (
        weights["figure_resemblance"] * float(rep.figure_resemblance.get("score", 0.0))
        + weights["panel_dominance"] * float(rep.panel_dominance.get("score", 0.0))
        + weights["hinge_axis_visibility"]
            * float(rep.hinge_axis_visibility.get("score", 0.0))
        + weights["floating_components"] * float(rep.floating_components.get("score", 0.0))
        + weights["demo_readability"] * float(rep.demo_readability.get("score", 0.0))
        + weights["v11"] * float(rep.v11_carryover.get("v11_composite", 0.0))
    )
    rep.overall = {
        "composite": round(composite, 3),
        "weights": weights,
        "verdict_short": rep.demo_readability.get("verdict", "unknown"),
    }
    return rep


def write_v12_report(rep: V12EvalReport, *, report_dir: Path) -> tuple[Path, Path]:
    md = []
    md.append(f"# Claim2CAD v1.2 evaluation — {rep.example_id}\n")
    md.append(f"**Composite: {rep.overall.get('composite', 0):.3f}** "
               f"(verdict: *{rep.overall.get('verdict_short', '?')}*)\n")
    md.append("## Visual axes (the human-aligned ones)\n")
    md.append("| metric | score | detail |")
    md.append("|---|---:|---|")
    for name, axis in (
        ("figure_resemblance", rep.figure_resemblance),
        ("panel_dominance", rep.panel_dominance),
        ("hinge_axis_visibility", rep.hinge_axis_visibility),
        ("floating_components", rep.floating_components),
        ("demo_readability", rep.demo_readability),
    ):
        score = axis.get("score", 0)
        detail = ", ".join(f"{k}={v}" for k, v in axis.items()
                            if k != "score" and not isinstance(v, list))
        md.append(f"| `{name}` | {float(score):.3f} | {detail} |")
    md.append("")
    md.append("## V11 axes (carryover — structural correctness)\n")
    md.append(f"V11 composite: **{rep.v11_carryover.get('v11_composite', 0):.3f}**\n")
    md.append("| axis | score |")
    md.append("|---|---:|")
    for k, v in (rep.v11_carryover.get("axis_scores") or {}).items():
        md.append(f"| `{k}` | {float(v):.3f} |")
    md.append("")
    md.append("## Notes")
    if not rep.notes:
        md.append("(none)")
    else:
        for n in rep.notes:
            md.append(f"- {n}")
    md.append("")
    md.append("## Visual artefacts to inspect")
    for art in (
        "renders_v1.2/readable_figure_aligned.png",
        "renders_v1.2/readable_iso.png",
        "renders_v1.2/readable_exploded.png",
        "renders_v1.2/solid_comparison.png",
        "renders_v1.2/hotspot_quality_debug.png",
        "renders_v1.2/figure_projection_lock_debug.png",
    ):
        ap = Path(rep.example_dir) / art
        if ap.exists():
            md.append(f"- `{art}`")
    md.append("")
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"{rep.example_id}_v12_eval.md"
    json_path = report_dir / f"{rep.example_id}_v12_eval.json"
    md_path.write_text("\n".join(md), encoding="utf-8")
    json_path.write_text(json.dumps(rep.to_dict(), indent=2) + "\n",
                          encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="V1.2 human-aligned evaluator")
    p.add_argument("example_dir", type=Path)
    p.add_argument("--report-dir", type=Path, default=Path("examples/reports"))
    args = p.parse_args(argv)
    rep = evaluate_example_v12(args.example_dir)
    md, jp = write_v12_report(rep, report_dir=args.report_dir)
    print(json.dumps(rep.to_dict(), indent=2))
    print(f"\nWrote {md}\nWrote {jp}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
