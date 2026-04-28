"""Iterative refinement loop (V11-4).

Pipeline:
  1. Generate the initial assembly from V11-3's figure_spec.
  2. Render and ask the VLM for a SimilarityReport (whole-assembly score
     + per-component defects).
  3. Pick the components flagged with major / moderate defects.
  4. Ask the VLM for a revised set of ComponentSpec rows for those
     components: new params, new position_mm, new rotation_deg.
  5. Merge revisions into the FigureSpec, rebuild, save iteration N.
  6. Stop when the overall score reaches ``target_score``, no measurable
     improvement happens between iterations, or the iteration budget is
     spent. Cost-capped: stops short if approaching the soft cap.

The output for each iteration is committed to disk so the loop can resume
from any iteration if interrupted.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import build123d as bd

from claim2cad.cost_tracker import cumulative_cost
from claim2cad.figure_to_cad import (
    ComponentSpec,
    FigureSpec,
    generate_assembly,
    run_generator,
)
from claim2cad.glb_naming import rename_glb_root_children
from claim2cad.ir_schema import ClaimIR
from claim2cad.llm_vision import vision_completion
from claim2cad.visual_validator import (
    DEFAULT_VIEWS,
    SimilarityReport,
    compare_to_figure,
    render_step_to_pngs,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Refinement record (per iteration)
# ---------------------------------------------------------------------------


@dataclass
class IterationRecord:
    iteration: int
    score: float
    silhouette: float = 0.0
    proportion: float = 0.0
    feature: float = 0.0
    arrangement: float = 0.0
    defect_count: int = 0
    refined_components: list[str] = field(default_factory=list)
    notes: str = ""
    cost_usd_so_far: float = 0.0

    def as_row(self) -> str:
        cols = [
            f"{self.iteration:02d}",
            f"{self.score:0.1f}",
            f"sil={self.silhouette:0.1f}",
            f"prop={self.proportion:0.1f}",
            f"feat={self.feature:0.1f}",
            f"arr={self.arrangement:0.1f}",
            f"defects={self.defect_count}",
            f"refined={','.join(self.refined_components) or '-'}",
            f"cost=${self.cost_usd_so_far:0.3f}",
        ]
        return "  ".join(cols)


# ---------------------------------------------------------------------------
# VLM prompt — revise the worst components
# ---------------------------------------------------------------------------


_REFINE_SYSTEM_PROMPT = (
    "You are improving a CAD assembly to better match a patent drawing. "
    "Given the figure, the current rendered assembly, the current parametric "
    "spec for the worst-performing components, and the defect list from a "
    "review, propose REVISED ComponentSpec rows for those components only. "
    "Keep ALL other components unchanged. Respect the registered library "
    "parts. Always return valid JSON."
)


_REFINE_USER_TEMPLATE = """The image attached is a side-by-side composite:
LEFT — the patent drawing.
RIGHT — multi-view renders of the candidate CAD assembly (current state).

Patent context: {patent_context}
Current overall score: {score}/10.
Per-axis scores: silhouette={sil}, proportion={prop}, feature={feat},
arrangement={arr}.

Defects to address (from the previous review):
{defect_list}

The components flagged for refinement (current spec rows):
{current_specs}

Registered library parts available:
  plate, leaf, rod, l_bracket, u_bracket, pin,
  leaf_hinge, revolute_joint, prismatic_joint,
  spur_gear, ball_bearing, helical_spring.

CRITICAL: For any component whose current `notes` contains "codegen",
keep its `library_part`, `params`, and `notes` EXACTLY as-is. You may
ONLY revise `position_mm` and `rotation_deg` for those — the geometry
was VLM-synthesised from the figure crop and must not be re-mapped to
a library shape. For components with library_part set, you may revise
params, position, and rotation freely.

Return JSON in this EXACT shape (revisions only — do not include
unchanged components):
{{
  "components": [
    {{
      "component_id": "<must match a flagged id>",
      "library_part": "<library name or null>",
      "params": {{"<name>": <number>, ...}},
      "position_mm": [<x>, <y>, <z>],
      "rotation_deg": [<rx>, <ry>, <rz>],
      "features": ["<short>", ...],
      "notes": "<optional 1 line>"
    }}
  ],
  "explanation": "<1-2 sentences on what changed and why>"
}}
"""


def _format_defect_list(defects: list[dict[str, Any]]) -> str:
    if not defects:
        return "  (no defects flagged)"
    rows: list[str] = []
    for d in defects:
        comp = d.get("component", "?")
        issue = d.get("issue", "?")
        sev = d.get("severity", "?")
        rows.append(f"  - [{sev}] {comp}: {issue}")
    return "\n".join(rows)


def _format_current_specs(specs: list[ComponentSpec]) -> str:
    return json.dumps(
        [asdict(s) for s in specs],
        indent=2,
        ensure_ascii=False,
    )


def _pick_components_to_refine(
    report: SimilarityReport,
    spec: FigureSpec,
    *,
    max_components: int = 5,
) -> list[ComponentSpec]:
    """Select the worst components from the defect list. Ordered by
    severity major > moderate > minor, deduplicated, capped at
    ``max_components``."""
    severity_rank = {"major": 0, "moderate": 1, "minor": 2}
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for d in sorted(
        report.defects,
        key=lambda r: severity_rank.get(str(r.get("severity", "minor")).lower(), 9),
    ):
        cid = d.get("component")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ordered_ids.append(cid)
        if len(ordered_ids) >= max_components:
            break
    spec_by_id = {s.component_id: s for s in spec.components}
    return [spec_by_id[cid] for cid in ordered_ids if cid in spec_by_id]


def _request_refinements(
    flagged: list[ComponentSpec],
    report: SimilarityReport,
    composite_path: Path,
    *,
    patent_context: str,
    task_type: str = "v11_refinement",
) -> tuple[list[ComponentSpec], str]:
    """Send the composite + flagged specs to the VLM, parse revised specs."""
    prompt = _REFINE_USER_TEMPLATE.format(
        patent_context=patent_context or "(none)",
        score=report.overall_score,
        sil=report.silhouette_score,
        prop=report.proportion_score,
        feat=report.feature_score,
        arr=report.arrangement_score,
        defect_list=_format_defect_list(report.defects),
        current_specs=_format_current_specs(flagged),
    )
    raw = vision_completion(
        image_path=composite_path,
        system_prompt=_REFINE_SYSTEM_PROMPT,
        user_prompt=prompt,
        task_type=task_type,
    )
    revised: list[ComponentSpec] = []
    flagged_ids = {s.component_id for s in flagged}
    for row in (raw.get("components") or []):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("component_id", "")).strip()
        if cid not in flagged_ids:
            continue
        try:
            pos = tuple(float(v) for v in row.get("position_mm", (0, 0, 0)))[:3]
            if len(pos) < 3:
                pos = pos + (0.0,) * (3 - len(pos))
        except (TypeError, ValueError):
            pos = (0.0, 0.0, 0.0)
        try:
            rot = tuple(float(v) for v in row.get("rotation_deg", (0, 0, 0)))[:3]
            if len(rot) < 3:
                rot = rot + (0.0,) * (3 - len(rot))
        except (TypeError, ValueError):
            rot = (0.0, 0.0, 0.0)
        revised.append(
            ComponentSpec(
                component_id=cid,
                library_part=row.get("library_part") or None,
                params=row.get("params") if isinstance(row.get("params"), dict) else {},
                position_mm=pos,  # type: ignore[arg-type]
                rotation_deg=rot,  # type: ignore[arg-type]
                features=[str(f) for f in (row.get("features") or []) if f],
                notes=str(row.get("notes", "")),
            )
        )
    explanation = str(raw.get("explanation", ""))
    return revised, explanation


def _merge_revisions(spec: FigureSpec, revisions: list[ComponentSpec]) -> FigureSpec:
    """Return a new FigureSpec with ``revisions`` overriding by component_id.

    For codegen components (current notes contain "codegen"), we preserve
    library_part / params / notes / features and only accept position +
    rotation revisions. The VLM is told this in the prompt; this is a
    second line of defence in case it slips up."""
    by_id = {s.component_id: s for s in spec.components}
    for r in revisions:
        existing = by_id.get(r.component_id)
        if existing is not None and "codegen" in (existing.notes or "").lower():
            r = ComponentSpec(
                component_id=r.component_id,
                library_part=existing.library_part,
                params=existing.params,
                position_mm=r.position_mm,
                rotation_deg=r.rotation_deg,
                features=existing.features,
                notes=existing.notes,
            )
        by_id[r.component_id] = r
    return FigureSpec(
        patent_id=spec.patent_id,
        figure_id=spec.figure_id,
        components=list(by_id.values()),
        raw=spec.raw,
    )


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def _write_iteration_artifacts(
    example_dir: Path,
    iteration: int,
    spec: FigureSpec,
    ir: ClaimIR,
    *,
    figure_crops: dict[str, Any] | None = None,
    code_cache_dir: Path | None = None,
    enable_codegen: bool = False,
) -> tuple[Path, Path]:
    """Build + write step/glb for one iteration and return (step_path, glb_path)."""
    # Per-iteration components dir avoids overwriting earlier iterations.
    components_dir = example_dir / f"components_iter{iteration:02d}"
    compound, ordered_ids, _ = generate_assembly(
        spec,
        ir,
        components_dir=components_dir,
        figure_crops=figure_crops,
        code_cache_dir=code_cache_dir,
        enable_codegen=enable_codegen,
    )
    suffix = f"_iter{iteration:02d}"
    step_path = example_dir / f"model_v1.1{suffix}.step"
    glb_path = example_dir / f"model_v1.1{suffix}.glb"
    bd.export_step(compound, str(step_path))
    bd.export_gltf(compound, str(glb_path), binary=True)
    try:
        rename_glb_root_children(glb_path, ordered_ids)
    except Exception as exc:  # noqa: BLE001 — naming is best-effort
        logger.warning("GLB rename failed at iteration %d: %s", iteration, exc)
    return step_path, glb_path


def _validate(
    example_dir: Path,
    step_path: Path,
    figure_path: Path,
    iteration: int,
    *,
    patent_context: str,
    component_list: list[str],
) -> tuple[SimilarityReport, Path]:
    """Render + validate a single iteration. Returns (report, composite_path)."""
    renders_dir = example_dir / f"renders_iter{iteration:02d}"
    renders = render_step_to_pngs(step_path, renders_dir)
    composite = example_dir / f"composite_iter{iteration:02d}.png"
    report = compare_to_figure(
        renders,
        figure_path,
        composite_path=composite,
        patent_context=patent_context,
        component_list=component_list,
        figure_label=figure_path.name,
        task_type="v11_refinement_validation",
    )
    return report, composite


def refine(
    example_dir: Path | str,
    *,
    figure_filename: str = "figures/figure_1.png",
    ir_filename: str = "claim_ir.json",
    initial_spec_filename: str = "figure_spec.json",
    max_iterations: int = 3,
    target_score: float = 8.0,
    cost_soft_cap: float = 70.0,
    patent_context: str = "",
    enable_codegen: bool = True,
) -> dict[str, Any]:
    """Run the iterative refinement loop on ``example_dir``.

    Stopping criteria (any one):
      * overall score >= ``target_score``,
      * ``max_iterations`` elapsed,
      * cumulative session cost crosses ``cost_soft_cap``,
      * no improvement (score didn't increase) for two consecutive iterations.

    Returns a dict summary suitable for JSON dump.
    """
    example_dir = Path(example_dir)
    figure_path = example_dir / figure_filename
    ir_path = example_dir / ir_filename
    initial_spec_path = example_dir / initial_spec_filename
    if not figure_path.exists() or not ir_path.exists() or not initial_spec_path.exists():
        raise FileNotFoundError(
            "refine() requires figure, claim_ir.json, and figure_spec.json to exist; "
            "run claim2cad.figure_to_cad first."
        )

    ir = ClaimIR.model_validate_json(ir_path.read_text("utf-8"))
    spec = FigureSpec.from_dict(json.loads(initial_spec_path.read_text("utf-8")))
    component_list = [c.id + ": " + c.label for c in ir.components]

    # Reuse the figure crops + codegen cache the figure_to_cad stage
    # produced. If they don't exist (e.g. user ran an earlier figure_to_cad
    # before this code shipped), regenerate now.
    from claim2cad.figure_crops import crop_all_components, crops_by_component_id

    figure_crops_dict: dict[str, Any] = {}
    figure_map_path = example_dir / "figure_map.json"
    if figure_map_path.exists():
        try:
            fmap = json.loads(figure_map_path.read_text("utf-8"))
            crops = crop_all_components(
                figure_path,
                fmap,
                out_dir=example_dir / "crops",
                crop_radius=0.12,
            )
            figure_crops_dict = crops_by_component_id(crops)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refresh figure crops: %s", exc)
    code_cache_dir = example_dir / "codegen_cache"

    history: list[IterationRecord] = []
    last_two_scores: list[float] = []
    final_step: Path | None = None
    final_glb: Path | None = None
    final_composite: Path | None = None
    final_report: SimilarityReport | None = None
    best_score: float = -1.0
    best_step: Path | None = None
    best_glb: Path | None = None
    best_composite: Path | None = None
    best_report: SimilarityReport | None = None
    best_iteration: int = 0

    for it in range(max_iterations + 1):
        # Iteration 0 = build + validate the input spec as-is.
        step_path, glb_path = _write_iteration_artifacts(
            example_dir,
            it,
            spec,
            ir,
            figure_crops=figure_crops_dict,
            code_cache_dir=code_cache_dir,
            enable_codegen=enable_codegen,
        )
        report, composite = _validate(
            example_dir,
            step_path,
            figure_path,
            it,
            patent_context=patent_context,
            component_list=component_list,
        )
        cost = cumulative_cost()
        record = IterationRecord(
            iteration=it,
            score=float(report.overall_score),
            silhouette=float(report.silhouette_score),
            proportion=float(report.proportion_score),
            feature=float(report.feature_score),
            arrangement=float(report.arrangement_score),
            defect_count=len(report.defects),
            refined_components=[],
            notes=report.notes,
            cost_usd_so_far=cost,
        )
        history.append(record)
        logger.info("Iteration %d: %s", it, record.as_row())
        final_step, final_glb, final_composite, final_report = step_path, glb_path, composite, report
        # Track the best-scoring iteration so we can promote it to the
        # canonical model_v1.1 paths regardless of where the loop halts.
        if record.score > best_score:
            best_score = record.score
            best_step = step_path
            best_glb = glb_path
            best_composite = composite
            best_report = report
            best_iteration = it

        if record.score >= target_score:
            logger.info("Reached target score %.1f at iteration %d", target_score, it)
            break
        if cost >= cost_soft_cap:
            logger.warning("Cost soft cap %.2f reached; halting refinement", cost_soft_cap)
            break
        last_two_scores.append(record.score)
        if len(last_two_scores) >= 3 and last_two_scores[-1] <= last_two_scores[-3]:
            logger.warning(
                "No improvement in last 2 iterations (%s); halting",
                last_two_scores[-3:],
            )
            break

        if it == max_iterations:
            break  # already validated final state

        # Refinement step: ask VLM for revised specs.
        flagged = _pick_components_to_refine(report, spec)
        if not flagged:
            logger.info("No flagged components — halting (likely all minor)")
            break
        revisions, explanation = _request_refinements(
            flagged,
            report,
            composite,
            patent_context=patent_context,
        )
        if not revisions:
            logger.info("VLM proposed no revisions — halting")
            break
        record.refined_components = [r.component_id for r in revisions]
        # Re-write the line we just appended so the log captures who got revised.
        history[-1] = record
        spec = _merge_revisions(spec, revisions)
        # Persist the revised spec for next iteration / debugging.
        (example_dir / f"figure_spec_iter{it+1:02d}.json").write_text(
            json.dumps(spec.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.info("Iteration %d → revisions: %s. %s", it, record.refined_components, explanation)

    # Promote BEST-scoring iteration (not the last) to the canonical names.
    # Refinements can regress, and the v1.1 deliverable is "the best CAD we
    # produced", not "the most recently produced CAD".
    promote_step = best_step if best_step is not None else final_step
    promote_glb = best_glb if best_glb is not None else final_glb
    promote_composite = best_composite if best_composite is not None else final_composite
    if promote_step is not None and promote_glb is not None:
        (example_dir / "model_v1.1.step").write_bytes(promote_step.read_bytes())
        (example_dir / "model_v1.1.glb").write_bytes(promote_glb.read_bytes())
    if promote_composite is not None:
        (example_dir / "render_comparison.png").write_bytes(promote_composite.read_bytes())

    summary = {
        "iterations": [asdict(r) for r in history],
        "final_score": history[-1].score if history else 0.0,
        "best_score": max((r.score for r in history), default=0.0),
        "best_iteration": best_iteration,
        "target_score": target_score,
        "max_iterations": max_iterations,
        "stopped_reason": _stop_reason(history, target_score, max_iterations, cost_soft_cap),
        "model_v1.1_step": str(example_dir / "model_v1.1.step"),
        "model_v1.1_glb": str(example_dir / "model_v1.1.glb"),
        "render_comparison_png": str(example_dir / "render_comparison.png"),
    }
    (example_dir / "refinement_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    # The refinement_log uses the best report's defects, since that's the
    # state we promote to model_v1.1.
    log_report = best_report if best_report is not None else final_report
    _write_refinement_log(example_dir, history, log_report, summary)
    return summary


def _stop_reason(
    history: list[IterationRecord],
    target_score: float,
    max_iterations: int,
    cost_soft_cap: float,
) -> str:
    if not history:
        return "no-iterations"
    last = history[-1]
    if last.score >= target_score:
        return f"reached target_score {target_score}"
    if last.cost_usd_so_far >= cost_soft_cap:
        return f"hit cost_soft_cap ${cost_soft_cap:.2f}"
    if last.iteration >= max_iterations:
        return f"max_iterations {max_iterations}"
    if len(history) >= 3 and history[-1].score <= history[-3].score:
        return "no improvement for 2 iterations"
    return "halted-other"


def _write_refinement_log(
    example_dir: Path,
    history: list[IterationRecord],
    final_report: SimilarityReport | None,
    summary: dict[str, Any],
) -> Path:
    """Write a human-readable refinement_log.md."""
    lines: list[str] = []
    lines.append("# Refinement Log\n")
    lines.append(
        f"Stopped: **{summary['stopped_reason']}** at iteration "
        f"{history[-1].iteration if history else 0} with overall score "
        f"**{summary['final_score']:.1f}/10** "
        f"(best across run: {summary['best_score']:.1f}).\n"
    )
    lines.append("## Iterations\n")
    lines.append("| iter | score | sil | prop | feat | arr | defects | refined | cost $ |")
    lines.append("|----:|------:|----:|----:|----:|----:|--------:|---------|------:|")
    for r in history:
        lines.append(
            f"| {r.iteration:02d} | {r.score:.1f} | {r.silhouette:.1f} | "
            f"{r.proportion:.1f} | {r.feature:.1f} | {r.arrangement:.1f} | "
            f"{r.defect_count} | "
            f"{', '.join(r.refined_components) or '-'} | {r.cost_usd_so_far:.3f} |"
        )
    if final_report is not None:
        lines.append("\n## Final defects\n")
        if not final_report.defects:
            lines.append("(none)")
        for d in final_report.defects:
            lines.append(
                f"- **[{d.get('severity','?')}]** "
                f"`{d.get('component','?')}` — {d.get('issue','?')}"
            )
        if final_report.notes:
            lines.append("\n## Final notes\n")
            lines.append(final_report.notes)
    out_path = example_dir / "refinement_log.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Iterative refinement loop (V11-4).")
    p.add_argument("example_dir", type=Path)
    p.add_argument("--figure", default="figures/figure_1.png")
    p.add_argument("--ir", default="claim_ir.json")
    p.add_argument("--spec", default="figure_spec.json")
    p.add_argument("--max-iters", type=int, default=3)
    p.add_argument("--target-score", type=float, default=8.0)
    p.add_argument("--cost-soft-cap", type=float, default=70.0)
    p.add_argument("--patent-context", default="")
    p.add_argument(
        "--no-codegen",
        action="store_true",
        help="Disable VLM build123d codegen during refinement.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CLAIM2CAD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)-22s :: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    args = _build_argparser().parse_args(argv)
    summary = refine(
        args.example_dir,
        figure_filename=args.figure,
        ir_filename=args.ir,
        initial_spec_filename=args.spec,
        max_iterations=args.max_iters,
        target_score=args.target_score,
        cost_soft_cap=args.cost_soft_cap,
        patent_context=args.patent_context,
        enable_codegen=not args.no_codegen,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
