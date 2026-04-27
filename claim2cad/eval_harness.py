"""V1-11 evaluation harness.

Runs the pipeline against a set of (claim.txt, expected_ir.json) pairs
and reports five families of metrics:

1. **Component extraction** — precision / recall on component IDs and on
   ``(label, kind)`` pairs (kinds matter; IDs are nominally noisy).
2. **Relation extraction** — precision / recall on directed
   ``(source, kind, target)`` triples.
3. **Figure mapping coverage** — fraction of components carrying a
   ``figure_number``.
4. **CAD generation success** — STEP and GLB files exist and exceed a
   size threshold (proxy for non-empty geometry).
5. **Claim-to-component mapping coverage** — fraction of components
   whose ``source_span`` slices to a non-empty substring of the
   referenced claim's text.

All numbers are reported per-example and as macro / micro aggregates.
The harness emits both JSON (machine-readable) and Markdown (human
read) reports.

CLI::

    python -m claim2cad.eval_harness \\
        --examples examples/golden_robot_arm examples/korean_robot_arm \\
                   examples/multi_claim_drone \\
        --out logs/eval_report
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from claim2cad.ir_schema import ClaimIR
from claim2cad.pipeline import run_pipeline

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BENCHMARK = [
    REPO_ROOT / "examples" / "golden_robot_arm",
    REPO_ROOT / "examples" / "hinge_assembly",
    REPO_ROOT / "examples" / "planetary_gear",
    REPO_ROOT / "examples" / "korean_robot_arm",
    REPO_ROOT / "examples" / "multi_claim_drone",
]


@dataclass
class PRMetric:
    """Precision / recall / F1, plus raw TP/FP/FN counts."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0 if self.fn == 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def add(self, other: "PRMetric") -> "PRMetric":
        return PRMetric(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)


@dataclass
class ExampleResult:
    example_id: str
    expected_components: int = 0
    actual_components: int = 0
    component_ids: PRMetric = field(default_factory=PRMetric)
    component_kinds: PRMetric = field(default_factory=PRMetric)
    relation_triples: PRMetric = field(default_factory=PRMetric)
    figure_coverage: float = 0.0
    cad_step_ok: bool = False
    cad_glb_ok: bool = False
    span_coverage: float = 0.0
    claim_count: int = 0
    error: Optional[str] = None


def _component_id_set(ir: ClaimIR) -> set[str]:
    return {c.id for c in ir.components}


def _component_kind_set(ir: ClaimIR) -> set[tuple[str, str]]:
    """Return ``{(category, kind)}`` — kind is what matters semantically.

    Using ``(category, kind)`` rather than ``id`` keeps the metric
    robust to LLM ID-naming variation; the ``test_korean_parser_*``
    tests showed that two valid parses can use different IDs but the
    same kinds.
    """
    return {(c.category, c.kind) for c in ir.components}


def _relation_triples(ir: ClaimIR) -> set[tuple[str, str, str]]:
    return {(r.source, r.kind, r.target) for r in ir.relations}


def _figure_coverage(ir: ClaimIR) -> float:
    if not ir.components:
        return 0.0
    n = sum(1 for c in ir.components if c.figure_number)
    return n / len(ir.components)


def _span_coverage(ir: ClaimIR) -> float:
    if not ir.components:
        return 0.0
    by_claim = {c.id: c.text for c in ir.claims}
    n = 0
    for comp in ir.components:
        ct = by_claim.get(comp.source_span.claim_id, "")
        slice_ = ct[comp.source_span.char_start : comp.source_span.char_end]
        if slice_.strip():
            n += 1
    return n / len(ir.components)


def _pr_from_sets(actual: set, expected: set) -> PRMetric:
    return PRMetric(
        tp=len(actual & expected),
        fp=len(actual - expected),
        fn=len(expected - actual),
    )


def evaluate_example(
    example_dir: Path,
    *,
    cad_size_threshold: int = 1024,
    write_outputs_to: Path | None = None,
    mode: str = "dryrun",
) -> ExampleResult:
    """Run the pipeline on ``example_dir`` and grade it against
    ``expected_ir.json``.

    Modes:
      - ``"dryrun"`` (default): replay ``expected_ir.json`` as input.
        Tests the pipeline roundtrip; metrics will be ~1.0 by construction.
      - ``"stub"``: parse with no API key (deterministic stub path).
        Tests the rule-based extractor's accuracy.
      - ``"llm"``: parse via the LLM. Requires ``OPENROUTER_API_KEY``.

    The run goes into a temporary directory unless ``write_outputs_to``
    is given.
    """
    expected_ir_path = example_dir / "expected_ir.json"
    claim_path = example_dir / "claim.txt"
    if not expected_ir_path.exists() or not claim_path.exists():
        return ExampleResult(
            example_id=example_dir.name,
            error="missing claim.txt or expected_ir.json",
        )

    expected = ClaimIR.model_validate_json(
        expected_ir_path.read_text(encoding="utf-8")
    )

    if write_outputs_to is None:
        out_dir = Path(tempfile.mkdtemp(prefix="claim2cad_eval_"))
        cleanup = True
    else:
        out_dir = write_outputs_to
        cleanup = False

    # In stub mode, force the parser into the deterministic path by
    # clearing the API key for the duration of this call.
    import os
    saved_key = os.environ.get("OPENROUTER_API_KEY")
    if mode == "stub" and saved_key:
        del os.environ["OPENROUTER_API_KEY"]

    try:
        dry_run = mode == "dryrun"
        artifacts = run_pipeline(
            claim_path=claim_path,
            out_dir=out_dir,
            dry_run=dry_run,
            write_generator=False,
        )
        actual = ClaimIR.model_validate_json(
            artifacts["claim_ir"].read_text(encoding="utf-8")
        )

        result = ExampleResult(
            example_id=example_dir.name,
            expected_components=len(expected.components),
            actual_components=len(actual.components),
            component_ids=_pr_from_sets(
                _component_id_set(actual), _component_id_set(expected)
            ),
            component_kinds=_pr_from_sets(
                _component_kind_set(actual), _component_kind_set(expected)
            ),
            relation_triples=_pr_from_sets(
                _relation_triples(actual), _relation_triples(expected)
            ),
            figure_coverage=_figure_coverage(actual),
            cad_step_ok=(
                artifacts["step"].exists()
                and artifacts["step"].stat().st_size >= cad_size_threshold
            ),
            cad_glb_ok=(
                artifacts["glb"].exists()
                and artifacts["glb"].stat().st_size >= cad_size_threshold
            ),
            span_coverage=_span_coverage(actual),
            claim_count=len(actual.claims),
        )
        return result
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Evaluation crashed on %s", example_dir.name)
        return ExampleResult(example_id=example_dir.name, error=str(exc))
    finally:
        if mode == "stub" and saved_key is not None:
            os.environ["OPENROUTER_API_KEY"] = saved_key
        if cleanup and out_dir.exists():
            import shutil

            shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class EvalReport:
    examples: list[ExampleResult] = field(default_factory=list)

    @property
    def n_evaluated(self) -> int:
        return sum(1 for e in self.examples if e.error is None)

    def aggregate_pr(self, attr: str) -> PRMetric:
        agg = PRMetric()
        for e in self.examples:
            if e.error:
                continue
            agg = agg.add(getattr(e, attr))
        return agg

    def macro_average(self, attr: str, metric: str = "f1") -> float:
        scores: list[float] = []
        for e in self.examples:
            if e.error:
                continue
            pr: PRMetric = getattr(e, attr)
            scores.append(getattr(pr, metric))
        return statistics.mean(scores) if scores else 0.0

    def average_float(self, attr: str) -> float:
        scores: list[float] = []
        for e in self.examples:
            if e.error:
                continue
            scores.append(getattr(e, attr))
        return statistics.mean(scores) if scores else 0.0

    def cad_success_rate(self) -> float:
        ok = sum(1 for e in self.examples if e.error is None and e.cad_step_ok and e.cad_glb_ok)
        total = sum(1 for e in self.examples if e.error is None)
        return ok / total if total else 0.0


def evaluate_all(example_dirs: list[Path], *, mode: str = "dryrun") -> EvalReport:
    report = EvalReport()
    for d in example_dirs:
        logger.info("Evaluating %s [mode=%s]", d.name, mode)
        report.examples.append(evaluate_example(d, mode=mode))
    return report


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_report_json(report: EvalReport) -> str:
    payload = {
        "summary": {
            "n_evaluated": report.n_evaluated,
            "cad_success_rate": round(report.cad_success_rate(), 3),
            "component_kind_micro_f1": round(
                report.aggregate_pr("component_kinds").f1, 3
            ),
            "component_kind_macro_f1": round(
                report.macro_average("component_kinds", "f1"), 3
            ),
            "component_id_micro_f1": round(
                report.aggregate_pr("component_ids").f1, 3
            ),
            "relation_micro_f1": round(report.aggregate_pr("relation_triples").f1, 3),
            "figure_coverage_avg": round(report.average_float("figure_coverage"), 3),
            "span_coverage_avg": round(report.average_float("span_coverage"), 3),
        },
        "examples": [],
    }
    for e in report.examples:
        d = asdict(e)
        for k in ("component_ids", "component_kinds", "relation_triples"):
            pr: PRMetric = getattr(e, k)
            d[k] = {
                "tp": pr.tp,
                "fp": pr.fp,
                "fn": pr.fn,
                "precision": round(pr.precision, 3),
                "recall": round(pr.recall, 3),
                "f1": round(pr.f1, 3),
            }
        d["figure_coverage"] = round(e.figure_coverage, 3)
        d["span_coverage"] = round(e.span_coverage, 3)
        payload["examples"].append(d)
    return json.dumps(payload, indent=2) + "\n"


def format_report_md(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append("# Claim2CAD evaluation report")
    lines.append("")
    lines.append(f"- Examples evaluated: **{report.n_evaluated}**")
    lines.append(
        f"- CAD generation success rate: **{report.cad_success_rate() * 100:.0f}%**"
    )
    lines.append(
        f"- Component (kind) micro-F1: **{report.aggregate_pr('component_kinds').f1:.3f}**"
    )
    lines.append(
        f"- Component (kind) macro-F1: **{report.macro_average('component_kinds', 'f1'):.3f}**"
    )
    lines.append(
        f"- Component (ID) micro-F1: **{report.aggregate_pr('component_ids').f1:.3f}**"
    )
    lines.append(
        f"- Relation triple micro-F1: **{report.aggregate_pr('relation_triples').f1:.3f}**"
    )
    lines.append(
        f"- Figure-mapping coverage: **{report.average_float('figure_coverage') * 100:.0f}%**"
    )
    lines.append(
        f"- Claim→component span coverage: **{report.average_float('span_coverage') * 100:.0f}%**"
    )
    lines.append("")
    lines.append("## Per-example breakdown")
    lines.append("")
    lines.append(
        "| example | n_comp_act / exp | kind_F1 | rel_F1 | fig_cov | span_cov | step | glb | claims |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|:---:|:---:|---:|"
    )
    for e in report.examples:
        if e.error:
            lines.append(
                f"| `{e.example_id}` | err | — | — | — | — | — | — | — |"
            )
            continue
        lines.append(
            "| `{eid}` | {ac}/{ec} | {kf:.3f} | {rf:.3f} | {fc:.0f}% | {sc:.0f}% | {step} | {glb} | {nc} |".format(
                eid=e.example_id,
                ac=e.actual_components,
                ec=e.expected_components,
                kf=e.component_kinds.f1,
                rf=e.relation_triples.f1,
                fc=e.figure_coverage * 100,
                sc=e.span_coverage * 100,
                step="✓" if e.cad_step_ok else "✗",
                glb="✓" if e.cad_glb_ok else "✗",
                nc=e.claim_count,
            )
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claim2cad.eval_harness",
        description="Run the V1-11 evaluation harness.",
    )
    p.add_argument(
        "--examples",
        nargs="*",
        type=Path,
        default=None,
        help="Example directories to evaluate. Defaults to the V1-11 benchmark set.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "logs" / "eval_report",
        help="Output prefix; writes <out>.json and <out>.md.",
    )
    p.add_argument(
        "--mode",
        choices=["dryrun", "stub", "llm"],
        default="dryrun",
        help=(
            "How to produce the actual IR. 'dryrun' replays "
            "expected_ir.json (CI-safe roundtrip); 'stub' tests the "
            "deterministic parser; 'llm' tests the full LLM path."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    examples = args.examples or DEFAULT_BENCHMARK
    report = evaluate_all([Path(p) for p in examples], mode=args.mode)

    out_json = args.out.with_suffix(".json")
    out_md = args.out.with_suffix(".md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(format_report_json(report), encoding="utf-8")
    out_md.write_text(format_report_md(report), encoding="utf-8")

    print(f"Wrote {out_json} and {out_md}")
    print()
    print(format_report_md(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
