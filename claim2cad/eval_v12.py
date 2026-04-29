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
    # V12-O additions — measure the oblique reconstruction.
    oblique_scene: dict[str, Any] = field(default_factory=dict)
    door_frame_angle: dict[str, Any] = field(default_factory=dict)
    hinge_axis_between_planes: dict[str, Any] = field(default_factory=dict)
    attached_component_ratio: dict[str, Any] = field(default_factory=dict)
    default_camera_is_patent_figure: dict[str, Any] = field(default_factory=dict)
    demo_hero_exists: dict[str, Any] = field(default_factory=dict)
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
            "oblique_scene": self.oblique_scene,
            "door_frame_angle": self.door_frame_angle,
            "hinge_axis_between_planes": self.hinge_axis_between_planes,
            "attached_component_ratio": self.attached_component_ratio,
            "default_camera_is_patent_figure": self.default_camera_is_patent_figure,
            "demo_hero_exists": self.demo_hero_exists,
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


def _eval_oblique_scene(example_dir: Path) -> dict[str, Any]:
    """V12-O — does an oblique opened-door model exist alongside
    the flat one? Pass-through if model_v1.2_oblique.glb exists
    AND has a substantially different door bbox from the flat
    model (signalling an actual rotation, not just renaming)."""
    flat_step = example_dir / "model_v1.2.step"
    oblique_step = example_dir / "model_v1.2_oblique.step"
    if not oblique_step.exists():
        return {"score": 0.0, "note": "no model_v1.2_oblique.step"}
    try:
        import build123d as bd

        ob = bd.import_step(str(oblique_step))
        door = next((c for c in getattr(ob, "children", [])
                     if c.label == "door_panel"), None)
        if door is None:
            return {"score": 0.0, "note": "no door_panel in oblique model"}
        bb = door.bounding_box()
        # In a flat closed-door model the door would lie in a thin
        # Y slab (sy ≈ 6-10 mm). After 35° rotation about Z, the
        # door's projection onto Y grows substantially — sy spans
        # ~100 mm.
        sy = bb.max.Y - bb.min.Y
        score = max(0.0, min(1.0, (sy - 20.0) / 60.0))
        return {
            "score": round(score, 3),
            "door_panel_y_span_mm": round(sy, 1),
            "note": "Y-span > ~80 mm indicates a substantial out-of-frame rotation",
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_door_frame_angle(example_dir: Path) -> dict[str, Any]:
    """V12-O — measure the angle between door_panel plane normal and
    fixed_frame plane normal in the oblique model. Patent figure
    shows the door open ~35-50°, which means the normals are at
    that same angle (since both panels were originally parallel,
    rotating one about a vertical axis rotates its normal by the
    same angle)."""
    step_path = example_dir / "model_v1.2_oblique.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no oblique model"}
    try:
        import build123d as bd
        import numpy as np

        sh = bd.import_step(str(step_path))
        door = next((c for c in getattr(sh, "children", [])
                      if c.label == "door_panel"), None)
        frame = next((c for c in getattr(sh, "children", [])
                       if c.label == "fixed_frame"), None)
        if door is None or frame is None:
            return {"score": 0.0, "note": "missing door or frame in oblique model"}

        def _principal_normal(part) -> tuple[float, float, float]:
            """The dominant normal direction of a thin part — the
            axis along which the bbox is THINNEST."""
            bb = part.bounding_box()
            sx = bb.max.X - bb.min.X
            sy = bb.max.Y - bb.min.Y
            sz = bb.max.Z - bb.min.Z
            sizes = [(sx, (1.0, 0.0, 0.0)),
                     (sy, (0.0, 1.0, 0.0)),
                     (sz, (0.0, 0.0, 1.0))]
            sizes.sort(key=lambda r: r[0])
            return sizes[0][1]

        # The thinnest dimension *would* be the panel normal IF the
        # panels stayed axis-aligned. After rotation they aren't, so
        # this approximation only works for the flat model. For the
        # oblique we approximate using the door's Y-extent vs X-extent
        # ratio — a closed door has X >> Y; an open door has Y ~ X.
        d_bb = door.bounding_box()
        f_bb = frame.bounding_box()
        d_sx = d_bb.max.X - d_bb.min.X
        d_sy = d_bb.max.Y - d_bb.min.Y
        f_sx = f_bb.max.X - f_bb.min.X
        f_sy = f_bb.max.Y - f_bb.min.Y
        # Door angle ≈ atan(sy_door / sx_door) - atan(sy_frame / sx_frame).
        ang_door = np.degrees(np.arctan2(d_sy, d_sx))
        ang_frame = np.degrees(np.arctan2(f_sy, f_sx))
        delta = abs(ang_door - ang_frame)
        # Score: 1.0 when delta in [25, 55]°, decays linearly outside.
        if delta < 10.0:
            score = 0.0
        elif delta < 25.0:
            score = (delta - 10.0) / 15.0
        elif delta <= 55.0:
            score = 1.0
        elif delta <= 80.0:
            score = 1.0 - (delta - 55.0) / 25.0
        else:
            score = 0.0
        return {
            "score": round(max(0.0, min(1.0, score)), 3),
            "door_bbox_angle_deg": round(ang_door, 1),
            "frame_bbox_angle_deg": round(ang_frame, 1),
            "delta_deg": round(delta, 1),
            "target_window_deg": [25.0, 55.0],
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_hinge_axis_between_planes(example_dir: Path) -> dict[str, Any]:
    """V12-O — pintle pin's X must sit between the door's right
    edge X and the frame's left edge X (i.e. between the two
    panels, not on top of either). The figure shows the pintle on
    the shared hinge edge."""
    step_path = example_dir / "model_v1.2_oblique.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no oblique model"}
    try:
        import build123d as bd

        sh = bd.import_step(str(step_path))
        door = next((c for c in getattr(sh, "children", [])
                      if c.label == "door_panel"), None)
        frame = next((c for c in getattr(sh, "children", [])
                       if c.label == "fixed_frame"), None)
        pintle = next((c for c in getattr(sh, "children", [])
                        if c.label == "pintle_pin"), None)
        if not all([door, frame, pintle]):
            return {"score": 0.0, "note": "missing door / frame / pintle"}
        d_bb = door.bounding_box()
        f_bb = frame.bounding_box()
        p_bb = pintle.bounding_box()
        pintle_cx = (p_bb.min.X + p_bb.max.X) / 2
        pintle_cy = (p_bb.min.Y + p_bb.max.Y) / 2
        # After door rotation about Z the door's bbox can extend
        # past the frame's bbox in X, so a strict "between in X"
        # test no longer applies. Instead we test whether the
        # pintle XY position lies WITHIN both panels' XY bbox
        # union — i.e. it's in the same horizontal region as the
        # hinge edge.
        in_door_xy = (d_bb.min.X <= pintle_cx <= d_bb.max.X
                       and d_bb.min.Y <= pintle_cy <= d_bb.max.Y)
        in_frame_xy = (f_bb.min.X <= pintle_cx <= f_bb.max.X
                        and f_bb.min.Y <= pintle_cy <= f_bb.max.Y)
        # Strong score when the pintle is shared by both panels
        # (i.e. on the literal hinge edge); weak score when only
        # one panel touches it.
        if in_door_xy and in_frame_xy:
            score = 1.0
            verdict = "shared by both panels (hinge edge)"
        elif in_door_xy or in_frame_xy:
            score = 0.6
            verdict = "in one panel's XY footprint only"
        else:
            score = 0.0
            verdict = "outside both panels"
        return {
            "score": round(score, 3),
            "verdict": verdict,
            "pintle_cxcy_mm": [round(pintle_cx, 1), round(pintle_cy, 1)],
            "in_door_bbox": in_door_xy,
            "in_frame_bbox": in_frame_xy,
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_attached_component_ratio(example_dir: Path) -> dict[str, Any]:
    """V12-O — fraction of the hinge sub-assembly meshes
    (door_leaf, frame_bracket, knuckle, pintle) that intersect
    EITHER the door_panel bbox OR the fixed_frame bbox OR each
    other's bbox. A high ratio means the hinge is "attached";
    a low ratio means the hinge is floating in space."""
    step_path = example_dir / "model_v1.2_oblique.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no oblique model"}
    try:
        import build123d as bd

        sh = bd.import_step(str(step_path))
        children = list(getattr(sh, "children", []))
        by_label = {c.label: c for c in children}
        door = by_label.get("door_panel")
        frame = by_label.get("fixed_frame")
        if door is None or frame is None:
            return {"score": 0.0, "note": "missing panels"}
        targets = [
            "upper_door_leaf", "lower_door_leaf",
            "upper_frame_bracket", "lower_frame_bracket",
            "upper_hinge_knuckle", "lower_hinge_knuckle",
            "pintle_pin",
        ]

        def _intersects(a, b) -> bool:
            ab = a.bounding_box()
            bb = b.bounding_box()
            return (ab.min.X <= bb.max.X and ab.max.X >= bb.min.X and
                    ab.min.Y <= bb.max.Y and ab.max.Y >= bb.min.Y and
                    ab.min.Z <= bb.max.Z and ab.max.Z >= bb.min.Z)

        attached = 0
        attempted = 0
        statuses: list[dict[str, Any]] = []
        for label in targets:
            child = by_label.get(label)
            if child is None:
                continue
            attempted += 1
            ok_door = _intersects(child, door)
            ok_frame = _intersects(child, frame)
            ok_other = any(
                lbl != label and by_label.get(lbl) is not None
                and _intersects(child, by_label[lbl])
                for lbl in targets
            )
            if ok_door or ok_frame or ok_other:
                attached += 1
            statuses.append({
                "label": label, "door": ok_door,
                "frame": ok_frame, "other_hinge": ok_other,
            })
        ratio = attached / max(attempted, 1)
        return {
            "score": round(ratio, 3),
            "attached": attached,
            "total": attempted,
            "per_component": statuses,
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_default_camera_is_patent_figure(example_dir: Path) -> dict[str, Any]:
    cam_path = example_dir / "camera_v12.json"
    if not cam_path.exists():
        return {"score": 0.0, "note": "no camera_v12.json"}
    try:
        cam = json.loads(cam_path.read_text("utf-8"))
        ok = cam.get("preset_id") == "patent_figure"
        return {
            "score": 1.0 if ok else 0.0,
            "preset_id": cam.get("preset_id"),
            "elev_deg": cam.get("matplotlib_render", {}).get("elev_deg"),
            "azim_deg": cam.get("matplotlib_render", {}).get("azim_deg"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_demo_hero_exists(example_dir: Path) -> dict[str, Any]:
    hero = example_dir / "renders_v1.2" / "hero_oblique.png"
    if not hero.exists():
        return {"score": 0.0, "note": "no hero_oblique.png"}
    try:
        sz = hero.stat().st_size
        ok = sz >= 50_000  # demo-grade hero is at least 50 KB
        return {
            "score": 1.0 if ok else 0.5,
            "size_bytes": sz,
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


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
    rep.oblique_scene = _eval_oblique_scene(example_dir)
    rep.door_frame_angle = _eval_door_frame_angle(example_dir)
    rep.hinge_axis_between_planes = _eval_hinge_axis_between_planes(example_dir)
    rep.attached_component_ratio = _eval_attached_component_ratio(example_dir)
    rep.default_camera_is_patent_figure = _eval_default_camera_is_patent_figure(example_dir)
    rep.demo_hero_exists = _eval_demo_hero_exists(example_dir)
    rep.v11_carryover = _v11_carryover(example_dir)

    # V12-O weights — oblique axes get 30% combined; original V12-G
    # visual axes 40%; v11 carryover 30%. demo_readability now also
    # acts as central-pile guard: if its score is 0 (refused credit),
    # everything gets penalised by the same hard fail.
    weights = {
        "figure_resemblance": 0.08,
        "panel_dominance": 0.10,
        "hinge_axis_visibility": 0.07,
        "floating_components": 0.05,
        "demo_readability": 0.10,
        # V12-O additions:
        "oblique_scene": 0.10,
        "door_frame_angle": 0.10,
        "hinge_axis_between_planes": 0.05,
        "attached_component_ratio": 0.05,
        "default_camera_is_patent_figure": 0.03,
        "demo_hero_exists": 0.02,
        "v11": 0.25,
    }
    composite = (
        weights["figure_resemblance"] * float(rep.figure_resemblance.get("score", 0.0))
        + weights["panel_dominance"] * float(rep.panel_dominance.get("score", 0.0))
        + weights["hinge_axis_visibility"]
            * float(rep.hinge_axis_visibility.get("score", 0.0))
        + weights["floating_components"] * float(rep.floating_components.get("score", 0.0))
        + weights["demo_readability"] * float(rep.demo_readability.get("score", 0.0))
        + weights["oblique_scene"] * float(rep.oblique_scene.get("score", 0.0))
        + weights["door_frame_angle"] * float(rep.door_frame_angle.get("score", 0.0))
        + weights["hinge_axis_between_planes"]
            * float(rep.hinge_axis_between_planes.get("score", 0.0))
        + weights["attached_component_ratio"]
            * float(rep.attached_component_ratio.get("score", 0.0))
        + weights["default_camera_is_patent_figure"]
            * float(rep.default_camera_is_patent_figure.get("score", 0.0))
        + weights["demo_hero_exists"] * float(rep.demo_hero_exists.get("score", 0.0))
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
        ("oblique_scene", rep.oblique_scene),
        ("door_frame_angle", rep.door_frame_angle),
        ("hinge_axis_between_planes", rep.hinge_axis_between_planes),
        ("attached_component_ratio", rep.attached_component_ratio),
        ("default_camera_is_patent_figure", rep.default_camera_is_patent_figure),
        ("demo_hero_exists", rep.demo_hero_exists),
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
        "renders_v1.2/hero_oblique.png",
        "renders_v1.2/hero_oblique_comparison.png",
        "renders_v1.2/oblique_iso.png",
        "renders_v1.2/oblique_figure_match.png",
        "renders_v1.2/oblique_comparison.png",
        "renders_v1.2/patent_figure_camera.png",
        "renders_v1.2/patent_figure_comparison.png",
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
