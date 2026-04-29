"""V11 evaluation harness — structural + visual.

Replaces the V1-11 single-VLM-score harness with a richer report that
runs entirely without LLM calls. Five metric families:

  1. **span_correctness** — fraction of components whose ``source_span``
     extracts the verified ``span_extracted`` from claim_map. The
     V11-13 relocator writes verified offsets; this re-checks them
     against the saved claim text to catch regressions.
  2. **glb_coverage** — fraction of components in claim_map.json whose
     glb_node_name appears as a top-level GLB node.
  3. **figure_callout_coverage** — fraction of figure_map numbered
     callouts that bind to a claim component.
  4. **geometric_invariants** — deterministic CAD-validity check:
     pin_through_holes, link_nests_in_main, door_wraps_assembly,
     bbox_sane, no_obvious_overlap.
  5. **projection_fit** — silhouette aspect-ratio match between the
     CAD's best canonical view and the patent figure (no VLM).

Output:
  * ``examples/reports/<example>_eval.md`` — human-readable.
  * ``examples/reports/<example>_eval.json`` — machine-readable.
  * Side-by-side images stay where they were already saved by V11-14.

Invocation: ``python -m claim2cad.eval_v11 examples/real_patents/<id>``.
"""
from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvalReport:
    example_id: str
    example_dir: str
    span_correctness: dict[str, Any] = field(default_factory=dict)
    glb_coverage: dict[str, Any] = field(default_factory=dict)
    figure_callout_coverage: dict[str, Any] = field(default_factory=dict)
    geometric_invariants: dict[str, Any] = field(default_factory=dict)
    projection_fit: dict[str, Any] = field(default_factory=dict)
    assembly_coherence: dict[str, Any] = field(default_factory=dict)  # V11-22
    projection_anchor_match: dict[str, Any] = field(default_factory=dict)  # V11-26
    central_density: dict[str, Any] = field(default_factory=dict)  # V11-26
    view_match: dict[str, Any] = field(default_factory=dict)  # V11-26
    hotspot_grounding: dict[str, Any] = field(default_factory=dict)  # V11-37
    overall: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-metric implementations
# ---------------------------------------------------------------------------


def _eval_span_correctness(example_dir: Path) -> dict[str, Any]:
    cm_path = example_dir / "claim_map.json"
    ir_path = example_dir / "claim_ir.json"
    if not cm_path.exists() or not ir_path.exists():
        return {"score": 0.0, "n_total": 0, "n_verified": 0, "note": "missing files"}
    cm = json.loads(cm_path.read_text("utf-8"))
    ir = json.loads(ir_path.read_text("utf-8"))
    claims_by_id = {c["id"]: c["text"] for c in ir["claims"]}
    rows = cm.get("components", [])
    verified = 0
    bad: list[str] = []
    for row in rows:
        if not row.get("span_verified", False):
            continue
        s = row["source_span"]
        text = claims_by_id.get(s["claim_id"], "")
        actual = text[s["char_start"] : s["char_end"]]
        expected = row.get("span_extracted", "")
        if expected and actual.strip().lower() == expected.strip().lower():
            verified += 1
        else:
            bad.append(row["component_id"])
    n_total = len(rows)
    score = verified / max(n_total, 1)
    return {
        "score": round(score, 3),
        "n_total": n_total,
        "n_verified": verified,
        "n_bad": len(bad),
        "bad_examples": bad[:5],
    }


def _glb_root_child_names(glb_path: Path) -> list[str]:
    if not glb_path.exists():
        return []
    blob = glb_path.read_bytes()
    if blob[:4] != b"glTF":
        return []
    json_len = struct.unpack("<I", blob[12:16])[0]
    parsed = json.loads(blob[20 : 20 + json_len].decode("utf-8"))
    scene = parsed["scenes"][parsed.get("scene", 0)]
    if not scene.get("nodes"):
        return []
    root = parsed["nodes"][scene["nodes"][0]]
    return [
        parsed["nodes"][ci].get("name", "")
        for ci in root.get("children", [])
        if parsed["nodes"][ci].get("name")
    ]


def _eval_glb_coverage(example_dir: Path) -> dict[str, Any]:
    cm_path = example_dir / "claim_map.json"
    glb_path = example_dir / "model_v1.1.glb"
    if not glb_path.exists():
        glb_path = example_dir / "model.glb"
    if not cm_path.exists() or not glb_path.exists():
        return {"score": 0.0, "n_components": 0, "n_in_glb": 0, "note": "missing files"}
    cm = json.loads(cm_path.read_text("utf-8"))
    component_ids = {row["component_id"] for row in cm.get("components", [])}
    glb_names = set(_glb_root_child_names(glb_path))
    matched = component_ids & glb_names
    score = len(matched) / max(len(component_ids), 1)
    return {
        "score": round(score, 3),
        "n_components": len(component_ids),
        "n_in_glb": len(matched),
        "missing_examples": sorted(component_ids - glb_names)[:5],
        "extra_glb_names": sorted(glb_names - component_ids)[:5],
    }


def _eval_figure_callout_coverage(example_dir: Path) -> dict[str, Any]:
    fm_path = example_dir / "figure_map.json"
    if not fm_path.exists():
        return {"score": 0.0, "n_callouts": 0, "n_bound": 0, "note": "no figure_map.json"}
    fm = json.loads(fm_path.read_text("utf-8"))
    labels = fm.get("vlm_labels") or []
    all_numbers = sorted({str(l.get("number", "")) for l in labels if l.get("number")})
    bound_numbers = sorted(set(map(str, (fm.get("component_to_number") or {}).values())))
    n_bound = len(set(bound_numbers) & set(all_numbers))
    score = n_bound / max(len(all_numbers), 1)
    return {
        "score": round(score, 3),
        "n_callouts": len(all_numbers),
        "n_bound": n_bound,
        "n_unbound": len(all_numbers) - n_bound,
    }


def _eval_geometric_invariants(example_dir: Path) -> dict[str, Any]:
    """Run the V11-10 invariants on the example's STEP."""
    step_path = example_dir / "model_v1.1.step"
    if not step_path.exists():
        step_path = example_dir / "model.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no STEP file"}
    try:
        import build123d as bd
        from claim2cad.geometric_invariants import evaluate_invariants
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}
    try:
        shape = bd.import_step(str(step_path))
        rep = evaluate_invariants(shape)
        return {
            "score": round(rep.composite(), 3),
            "pin_through_holes": rep.pin_through_holes,
            "link_nests_in_main": rep.link_nests_in_main,
            "door_wraps_assembly": rep.door_wraps_assembly,
            "bbox_sane": rep.bbox_sane,
            "no_obvious_overlap": rep.no_obvious_overlap,
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_projection_fit(example_dir: Path) -> dict[str, Any]:
    pr_path = example_dir / "projection_report.json"
    if not pr_path.exists():
        return {"score": 0.0, "note": "no projection_report.json"}
    pr = json.loads(pr_path.read_text("utf-8"))
    score = float(pr.get("best_aspect_score", 0.0) or 0.0)
    return {
        "score": round(score, 3),
        "best_view": pr.get("best_view", "?"),
        "n_views_rendered": len(pr.get("views", [])),
    }


def _eval_projection_anchor_match(example_dir: Path) -> dict[str, Any]:
    """V11-26 — does the CAD projection match the figure anchors?

    Reads ``figure_projection.json`` to get per-component (u, v)
    anchors and the matching CAD anchor. Then loads the built STEP,
    projects each labelled child's centre onto the figure plane, and
    compares.

    The lower the average anchor error, the better the projection
    tracks the figure. ``score = 1.0 - clamp(error / 50mm)``.
    """
    fp_path = example_dir / "figure_projection.json"
    if not fp_path.exists():
        return {"score": 0.0, "note": "no figure_projection.json"}
    step_path = example_dir / "model_v1.1.step"
    if not step_path.exists():
        return {"score": 0.0, "note": "no STEP file"}
    try:
        from claim2cad.figure_projection import load_layout
        import build123d as bd

        layout = load_layout(fp_path)
        anchors_by_id = {a.id: a for a in layout.component_anchors}
        shape = bd.import_step(str(step_path))
        proj = layout.projection
        idx = {"X": 0, "Y": 1, "Z": 2}
        ax_u, ax_v = proj.projection_plane
        u_idx = idx[ax_u]
        v_idx = idx[ax_v]
        errors: list[float] = []
        per_component: list[dict[str, Any]] = []
        for child in shape.children:
            cid = getattr(child, "label", "") or ""
            if not cid or cid.startswith("_scaffold_"):
                continue
            a = anchors_by_id.get(cid)
            if a is None:
                continue
            bb = child.bounding_box()
            cx = (bb.min.X + bb.max.X) / 2
            cy = (bb.min.Y + bb.max.Y) / 2
            cz = (bb.min.Z + bb.max.Z) / 2
            cad = (cx, cy, cz)
            # Distance in projection plane only.
            anchor = a.cad_anchor_mm
            du = cad[u_idx] - anchor[u_idx]
            dv = cad[v_idx] - anchor[v_idx]
            err = (du * du + dv * dv) ** 0.5
            errors.append(err)
            per_component.append(
                {"id": cid, "error_mm": round(err, 1)}
            )
        if not errors:
            return {"score": 0.0, "note": "no overlap between anchors and GLB"}
        mean_err = sum(errors) / len(errors)
        score = max(0.0, 1.0 - mean_err / 50.0)
        per_component.sort(key=lambda r: -r["error_mm"])
        return {
            "score": round(score, 3),
            "mean_error_mm": round(mean_err, 2),
            "max_error_mm": round(max(errors), 2),
            "n_anchors": len(errors),
            "worst": per_component[:5],
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_central_density(example_dir: Path) -> dict[str, Any]:
    """V11-26 — measures whether the figure-aligned render is a
    central pile. Reads ``renders_v1.1/figure_aligned_view.png`` (or
    falls back to ``solid_iso.png``); compares ink density in the
    central 30 % of the image to the outer ring."""
    candidates = [
        example_dir / "renders_v1.1" / "figure_aligned_view.png",
        example_dir / "renders_v1.1" / "solid_iso.png",
        example_dir / "renders_v1.1" / "projection_iso.png",
    ]
    img_path: Path | None = None
    for c in candidates:
        if c.exists():
            img_path = c
            break
    if img_path is None:
        return {"score": 0.0, "note": "no inspectable render available"}
    try:
        import numpy as np
        from PIL import Image

        arr = np.asarray(Image.open(img_path).convert("L"))
        ink = arr < 200  # any non-white pixel
        H, W = arr.shape
        cx0 = int(W * 0.35)
        cx1 = int(W * 0.65)
        cy0 = int(H * 0.35)
        cy1 = int(H * 0.65)
        central_pixels = ink[cy0:cy1, cx0:cx1].sum()
        central_area = (cx1 - cx0) * (cy1 - cy0)
        outer_pixels = ink.sum() - central_pixels
        outer_area = (W * H) - central_area
        central_density = float(central_pixels) / max(central_area, 1)
        outer_density = float(outer_pixels) / max(outer_area, 1)
        # Healthy ratio: central ≤ 2x outer. Pile-up: central >> outer.
        ratio = central_density / max(outer_density, 1e-6)
        # Score 1 if ratio ≤ 1, decays to 0 at ratio = 5.
        score = max(0.0, 1.0 - max(0.0, ratio - 1.0) / 4.0)
        return {
            "score": round(score, 3),
            "central_density": round(central_density, 4),
            "outer_density": round(outer_density, 4),
            "ratio": round(ratio, 2),
            "image": str(img_path.relative_to(example_dir)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "error": str(exc)}


def _eval_view_match(example_dir: Path) -> dict[str, Any]:
    """V11-26 — does the figure_view_classifier's ``view_kind`` match
    the projection_compare's chosen ``best_view`` (mapped to the same
    canonical plane)?"""
    fview_path = example_dir / "figure_view.json"
    pr_path = example_dir / "projection_report.json"
    if not fview_path.exists() or not pr_path.exists():
        return {"score": 0.0, "note": "missing figure_view.json or projection_report.json"}
    fv = json.loads(fview_path.read_text("utf-8"))
    pr = json.loads(pr_path.read_text("utf-8"))
    view_kind = (fv.get("view_kind") or "").lower()
    best = (pr.get("best_view") or "").lower()
    # Acceptable matches per view_kind (the figure-vs-CAD plane match).
    acceptable = {
        "top": {"top"},
        "bottom": {"top"},
        "front": {"front"},
        "back": {"front"},
        "right": {"right"},
        "left": {"right"},
        "iso": {"front", "iso"},
        "isometric": {"front", "iso"},
        "exploded": {"front", "iso"},
        "perspective": {"front", "iso"},
        "sectional": {"front", "iso"},
    }
    expected = acceptable.get(view_kind, {"front", "iso"})
    score = 1.0 if best in expected else 0.0
    return {
        "score": score,
        "view_kind": view_kind,
        "best_view": best,
        "expected": sorted(expected),
    }


def _eval_hotspot_grounding(example_dir: Path) -> dict[str, Any]:
    """V11-37 — figure-hotspot grounding metrics.

    Measures four things:
      1. **leader_line_detection_rate** — fraction of vlm_labels for
         which leader_lines.json found a Hough line. Tells us how
         many callouts have a *real* part anchor vs a fallback.
      2. **hotspot_source_distribution** — counts of part hotspots by
         source (leader_endpoint / projection_anchor / label_center /
         crop_center / median_label / manual_override). The leader
         fraction is what we actually want to maximise.
      3. **repeated_instance_count** — how many components have > 1
         hotspot instance preserved (V11-36 promise that upper/lower
         hinge duplicates aren't collapsed by median).
      4. **low_confidence_count** — part hotspots with conf < 0.5
         and **out_of_bounds_count** — part hotspots whose center_px
         is outside (0, image_width)×(0, image_height). Both should
         be 0 in a clean run.

    Composite score = 0.6·leader_rate + 0.3·repeated_instance_score +
                      0.1·in_bounds_score
    where ``repeated_instance_score`` rewards preserving > 0 repeats
    when the figure has duplicate callouts.
    """
    fh_path = example_dir / "figure_hotspots.json"
    fm_path = example_dir / "figure_map.json"
    if not fh_path.exists():
        return {"score": 0.0, "note": "no figure_hotspots.json"}
    fh = json.loads(fh_path.read_text("utf-8"))
    hotspots = fh.get("hotspots", []) or []
    part_hotspots = [h for h in hotspots if h.get("hotspot_kind", "part") == "part"]
    label_hotspots = [h for h in hotspots if h.get("hotspot_kind") == "label"]

    src_dist: dict[str, int] = {}
    for h in part_hotspots:
        src_dist[h.get("source", "unknown")] = src_dist.get(h.get("source", "unknown"), 0) + 1

    leader_grounded = src_dist.get("leader_endpoint", 0)
    leader_rate = leader_grounded / max(len(part_hotspots), 1)

    # leader_line_detection_rate uses the raw leader_lines.json file
    # rather than the post-fallback hotspot count, because some labels
    # have no claim component bound and thus never reach figure_hotspots.
    leader_total = 0
    leader_hits = 0
    leaders_path = example_dir / "leader_lines.json"
    if leaders_path.exists():
        try:
            ld = json.loads(leaders_path.read_text("utf-8"))
            for l in ld.get("leaders", []) or []:
                leader_total += 1
                if l.get("method") == "hough":
                    leader_hits += 1
        except Exception:  # noqa: BLE001
            pass
    detection_rate = leader_hits / max(leader_total, 1) if leader_total else 0.0

    instance_count_by_cid: dict[str, int] = {}
    for h in part_hotspots:
        cid = h.get("component_id") or ""
        instance_count_by_cid[cid] = instance_count_by_cid.get(cid, 0) + 1
    repeated_components = {cid: n for cid, n in instance_count_by_cid.items() if n > 1}

    # The figure has some callout numbers that appear twice; check
    # whether we *could* have preserved repeats.
    duplicate_callout_numbers = 0
    if fm_path.exists():
        fm = json.loads(fm_path.read_text("utf-8"))
        seen: dict[str, int] = {}
        for lab in fm.get("vlm_labels", []) or []:
            num = str(lab.get("number") or "").strip()
            if num:
                seen[num] = seen.get(num, 0) + 1
        duplicate_callout_numbers = sum(1 for n in seen.values() if n > 1)

    if duplicate_callout_numbers == 0:
        repeated_score = 1.0  # nothing to preserve, full credit
    else:
        repeated_score = min(1.0, len(repeated_components) / max(duplicate_callout_numbers, 1))

    low_confidence = sum(1 for h in part_hotspots if float(h.get("confidence", 0.5)) < 0.5)
    W = int(fh.get("image_width_px", 0) or 0)
    H = int(fh.get("image_height_px", 0) or 0)
    out_of_bounds = 0
    for h in part_hotspots:
        cx, cy = h.get("center_px", [0, 0])
        if not (0 <= cx <= W and 0 <= cy <= H):
            out_of_bounds += 1
    in_bounds_score = 1.0 - (out_of_bounds / max(len(part_hotspots), 1))

    score = 0.6 * detection_rate + 0.3 * repeated_score + 0.1 * in_bounds_score
    return {
        "score": round(score, 3),
        "leader_line_detection_rate": round(detection_rate, 3),
        "leader_lines_total": leader_total,
        "leader_lines_detected": leader_hits,
        "n_part_hotspots": len(part_hotspots),
        "n_label_hotspots": len(label_hotspots),
        "hotspot_source_distribution": src_dist,
        "leader_grounded_fraction": round(leader_rate, 3),
        "duplicate_callout_numbers": duplicate_callout_numbers,
        "repeated_instance_count": len(repeated_components),
        "repeated_components": sorted(repeated_components.keys())[:8],
        "low_confidence_count": low_confidence,
        "out_of_bounds_count": out_of_bounds,
    }


def _eval_assembly_coherence(example_dir: Path) -> dict[str, Any]:
    """V11-22 — penalises collage-like output. Reads the diagnostics
    cache (or runs the diagnostics in-process if it isn't present).

    The coherence score is **1 minus the collage score**: a well-laid-
    out assembly with separated panels and Z-separated hinge clusters
    scores high; a central pile scores low. The score also surfaces
    the per-axis sub-scores so the user can see *why* the assembly
    isn't coherent.
    """
    diag_path = example_dir / "assembly_diagnostics.json"
    diag: dict[str, Any] | None = None
    if diag_path.exists():
        try:
            diag = json.loads(diag_path.read_text("utf-8"))
        except json.JSONDecodeError:
            diag = None
    if diag is None:
        # Try to compute it from the STEP if no cache exists.
        step_path = example_dir / "model_v1.1.step"
        if not step_path.exists():
            step_path = example_dir / "model.step"
        if not step_path.exists():
            return {"score": 0.0, "note": "no STEP file or diagnostics cache"}
        try:
            from claim2cad.assembly_diagnostics import diagnose_step
            rep = diagnose_step(step_path)
            diag = rep.to_dict()
        except Exception as exc:  # noqa: BLE001
            return {"score": 0.0, "error": str(exc)}
    collage = float(diag.get("collage_score", 0.5) or 0.5)
    central = int(diag.get("central_cluster_count", 0) or 0)
    n_total = int(diag.get("n_components", 0) or 0)
    return {
        "score": round(1.0 - collage, 3),
        "collage_score": round(collage, 3),
        "central_cluster_count": central,
        "central_cluster_fraction": round(central / max(n_total, 1), 3),
        "z_separation_score": diag.get("z_separation_score", 0.0),
        "panel_separation_score": diag.get("panel_separation_score", 0.0),
        "pair_overlap_fraction": diag.get("pair_overlap_fraction", 0.0),
        "n_components": n_total,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def evaluate_example(example_dir: Path) -> EvalReport:
    example_dir = example_dir.resolve()
    report = EvalReport(
        example_id=example_dir.name,
        example_dir=str(example_dir),
    )
    report.span_correctness = _eval_span_correctness(example_dir)
    report.glb_coverage = _eval_glb_coverage(example_dir)
    report.figure_callout_coverage = _eval_figure_callout_coverage(example_dir)
    report.geometric_invariants = _eval_geometric_invariants(example_dir)
    report.projection_fit = _eval_projection_fit(example_dir)
    report.assembly_coherence = _eval_assembly_coherence(example_dir)
    report.projection_anchor_match = _eval_projection_anchor_match(example_dir)
    report.central_density = _eval_central_density(example_dir)
    report.view_match = _eval_view_match(example_dir)
    report.hotspot_grounding = _eval_hotspot_grounding(example_dir)

    # Composite weights. V11-37 adds hotspot_grounding (leader-line
    # rate + repeated-instance preservation + bounds) so the eval
    # surface reflects the click-through accuracy of the viewer.
    weights = {
        "span_correctness": 0.18,
        "glb_coverage": 0.13,
        "figure_callout_coverage": 0.05,
        "geometric_invariants": 0.10,
        "projection_fit": 0.04,
        "assembly_coherence": 0.13,
        "projection_anchor_match": 0.13,
        "central_density": 0.09,
        "view_match": 0.05,
        "hotspot_grounding": 0.10,
    }
    overall = 0.0
    for name, w in weights.items():
        s = float(getattr(report, name).get("score", 0.0))
        overall += w * s
    report.overall = {
        "composite": round(overall, 3),
        "weights": weights,
    }
    return report


def write_markdown_report(report: EvalReport, out_path: Path) -> Path:
    lines: list[str] = []
    lines.append(f"# Evaluation report — {report.example_id}\n")
    lines.append(f"**Composite score: {report.overall.get('composite', 0):.3f}**\n")
    lines.append("## Metric breakdown\n")
    lines.append("| metric | score | detail |")
    lines.append("|---|---:|---|")
    for name in (
        "span_correctness",
        "glb_coverage",
        "figure_callout_coverage",
        "geometric_invariants",
        "projection_fit",
        "assembly_coherence",
        "projection_anchor_match",
        "central_density",
        "view_match",
        "hotspot_grounding",
    ):
        m = getattr(report, name)
        score = m.get("score", 0)
        detail = ", ".join(
            f"{k}={v}" for k, v in m.items() if k != "score" and not isinstance(v, list)
        )
        lines.append(f"| `{name}` | {score:.3f} | {detail} |")
    lines.append("\n## Notes")
    if not report.notes:
        lines.append("(none)")
    else:
        for n in report.notes:
            lines.append(f"- {n}")
    lines.append("")

    # Reference paths the user should open.
    lines.append("## Visual artifacts")
    for art in (
        "figures/figure_1.png",
        "render_comparison.png",
        "renders_v1.1/projection_top.png",
        "renders_v1.1/projection_front.png",
        "renders_v1.1/projection_right.png",
        "renders_v1.1/projection_iso.png",
        "renders_v1.1/leader_line_debug.png",
        "renders_v1.1/figure_hotspot_debug.png",
        "renders_v1.1/figure_hotspot_triplets.png",
    ):
        ap = Path(report.example_dir) / art
        if ap.exists():
            lines.append(f"- `{art}`")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_json_report(report: EvalReport, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out_path


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="V11 structural + visual evaluation harness (no LLM calls)."
    )
    p.add_argument("example_dir", type=Path)
    p.add_argument("--report-dir", type=Path, default=Path("examples/reports"))
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    args = _build_argparser().parse_args(argv)
    if not args.example_dir.exists():
        sys.stderr.write(f"example dir not found: {args.example_dir}\n")
        return 2
    report = evaluate_example(args.example_dir)
    md_path = args.report_dir / f"{report.example_id}_eval.md"
    json_path = args.report_dir / f"{report.example_id}_eval.json"
    write_markdown_report(report, md_path)
    write_json_report(report, json_path)
    print(json.dumps(report.to_dict(), indent=2))
    print(f"\nWrote {md_path}\nWrote {json_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
