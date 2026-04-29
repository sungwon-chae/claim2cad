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

    # Composite score: weighted average. Span and glb coverage are the
    # hardest blockers (they affect interaction). Assembly coherence
    # was added in V11-22 because the scaffold rebuild moves visual
    # quality independently of the LLM-grounded metrics.
    weights = {
        "span_correctness": 0.25,
        "glb_coverage": 0.20,
        "figure_callout_coverage": 0.10,
        "geometric_invariants": 0.15,
        "projection_fit": 0.10,
        "assembly_coherence": 0.20,
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
