"""Batch validator for ``examples/real_patents/``.

Runs the v0.1.0 pipeline on every patent directory, captures structural
results to ``result.json``, and emits a markdown summary.

Quality grading heuristic (used for the V1-2 iterative improvement loop):

- **good** — parsed without LLM error; ≥4 components; CAD STEP+GLB generated;
  mapping_complete ≥ 0.9.
- **partial** — parsed with at least 2 components and CAD generated, but
  mapping_complete < 0.9 OR validation produced warnings.
- **fail** — parser raised, no CAD output, or fewer than 2 components.

The exact threshold values mirror the brief's "lenient pass" line.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from claim2cad.cost_tracker import cost_summary, cumulative_cost
from claim2cad.ir_schema import ClaimIR
from claim2cad.pipeline import run_pipeline

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PATENTS_DIR = REPO_ROOT / "examples" / "real_patents"


@dataclass
class PatentResult:
    patent_id: str
    parsed: bool
    components_count: int
    cad_generated: bool
    mapping_complete: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality_grade: str = "fail"
    duration_s: float = 0.0
    title: str = ""
    primary_class: str = "?"

    def as_dict(self) -> dict:
        return asdict(self)


def _read_metadata(patent_dir: Path) -> dict[str, Any]:
    p = patent_dir / "source_metadata.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _grade(result: PatentResult) -> str:
    if not result.parsed or not result.cad_generated or result.components_count < 2:
        return "fail"
    if result.components_count >= 4 and result.mapping_complete >= 0.9 and not result.warnings:
        return "good"
    return "partial"


def validate_one(patent_dir: Path) -> PatentResult:
    metadata = _read_metadata(patent_dir)
    patent_id = metadata.get("patent_id") or patent_dir.name.split("_", 1)[0]
    primary_class = metadata.get("primary_class", "?")
    title = metadata.get("title", "")

    result = PatentResult(
        patent_id=patent_id,
        parsed=False,
        components_count=0,
        cad_generated=False,
        mapping_complete=0.0,
        title=title,
        primary_class=primary_class,
    )

    claim_path = patent_dir / "claim.txt"
    if not claim_path.exists():
        result.errors.append("missing_claim_txt")
        result.quality_grade = "fail"
        return result

    start = time.time()
    try:
        artifacts = run_pipeline(
            claim_path=claim_path,
            out_dir=patent_dir,
            write_generator=True,
            example_name=patent_dir.name,
        )
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"pipeline_error: {type(exc).__name__}: {exc}")
        logger.exception("Pipeline failed for %s", patent_id)
        result.duration_s = round(time.time() - start, 2)
        result.quality_grade = "fail"
        return result

    result.duration_s = round(time.time() - start, 2)

    ir_path = artifacts.get("claim_ir")
    if ir_path and ir_path.exists():
        try:
            ir = ClaimIR.model_validate_json(ir_path.read_text(encoding="utf-8"))
            result.parsed = True
            result.components_count = len(ir.components)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"ir_validation: {exc!r}")
    else:
        result.errors.append("missing_claim_ir")

    step_path = artifacts.get("step")
    glb_path = artifacts.get("glb")
    if step_path and step_path.exists() and step_path.stat().st_size > 1000:
        if glb_path and glb_path.exists() and glb_path.stat().st_size > 1000:
            result.cad_generated = True
        else:
            result.warnings.append("glb_missing_or_tiny")
    else:
        result.warnings.append("step_missing_or_tiny")

    cmap_path = artifacts.get("claim_map")
    if cmap_path and cmap_path.exists():
        try:
            cmap = json.loads(cmap_path.read_text(encoding="utf-8"))
            cmap_count = len(cmap.get("components", []))
            if result.components_count > 0:
                result.mapping_complete = round(min(cmap_count, result.components_count) /
                                                result.components_count, 3)
            if cmap_count != result.components_count:
                result.warnings.append(
                    f"cmap_count_mismatch: cmap={cmap_count} ir={result.components_count}"
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"cmap_parse: {exc!r}")
    else:
        result.warnings.append("missing_claim_map")

    result.quality_grade = _grade(result)
    return result


def write_result(patent_dir: Path, result: PatentResult) -> None:
    (patent_dir / "result.json").write_text(
        json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def write_validation_report(
    results: list[PatentResult],
    *,
    iteration: int = 0,
    extra_context: str = "",
) -> Path:
    out = PATENTS_DIR / "COLLECTION_VALIDATION_REPORT.md"
    grades = Counter(r.quality_grade for r in results)
    err_categories: Counter[str] = Counter()
    for r in results:
        for e in r.errors:
            err_categories[_categorise(e)] += 1
        for w in r.warnings:
            err_categories[_categorise(w)] += 1

    lines: list[str] = ["# V1-2 — Pipeline Validation on Real Patents", ""]
    if iteration:
        lines.append(f"**Iteration:** {iteration}")
    lines.append(f"**Patents validated:** {len(results)}")
    lines.append("")
    lines.append("## Quality grade distribution")
    lines.append("")
    for grade in ("good", "partial", "fail"):
        lines.append(f"- **{grade}:** {grades.get(grade, 0)}")
    lines.append("")
    if err_categories:
        lines.append("## Failure / warning categories")
        lines.append("")
        for cat, count in err_categories.most_common():
            lines.append(f"- {cat}: {count}")
        lines.append("")

    lines.append("## Per-patent results")
    lines.append("")
    lines.append("| ID | Class | Grade | Comps | CAD | Map% | Time(s) | Issues |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: (x.quality_grade, x.patent_id)):
        issues = "; ".join((r.errors + r.warnings)[:3]) or "—"
        lines.append(
            f"| `{r.patent_id}` | {r.primary_class} | **{r.quality_grade}** | "
            f"{r.components_count} | {'✓' if r.cad_generated else '✗'} | "
            f"{int(r.mapping_complete*100)}% | {r.duration_s:.1f} | {issues[:80]} |"
        )

    if extra_context:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        lines.append(extra_context)

    summary = cost_summary()
    lines.append("")
    lines.append("## Cost (cumulative this session)")
    lines.append("")
    lines.append(f"- Total LLM calls: {summary['total_calls']}")
    lines.append(f"- Total spend: ${summary['total_cost_usd']:.3f}")
    if summary["by_task"]:
        lines.append("")
        lines.append("By task type:")
        for k, v in summary["by_task"].items():
            lines.append(f"- {k}: ${v:.3f}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


_FAILURE_CATEGORY_PATTERNS: list[tuple[str, str]] = [
    (r"validation", "ir-schema-validation-error"),
    (r"json", "llm-output-parse-error"),
    (r"timeout|timed out", "llm-timeout"),
    (r"http", "llm-http-error"),
    (r"step_missing|glb_missing", "cad-export-failure"),
    (r"cmap_count_mismatch", "ir-cad-count-mismatch"),
    (r"missing_claim_ir", "pipeline-no-ir"),
    (r"no module|importerror", "missing-dependency"),
    (r"refusing|rejected|denied", "external-rejection"),
]
import re as _re  # noqa: E402


def _categorise(message: str) -> str:
    msg = message.lower()
    for pat, label in _FAILURE_CATEGORY_PATTERNS:
        if _re.search(pat, msg):
            return label
    return "other"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_batch(patent_dirs: list[Path]) -> list[PatentResult]:
    results: list[PatentResult] = []
    for d in patent_dirs:
        logger.info("Validating %s", d.name)
        try:
            r = validate_one(d)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Outer failure on %s", d.name)
            r = PatentResult(
                patent_id=d.name.split("_", 1)[0],
                parsed=False,
                components_count=0,
                cad_generated=False,
                mapping_complete=0.0,
                errors=[f"outer_exception: {exc!r}"],
                quality_grade="fail",
                title=_read_metadata(d).get("title", ""),
                primary_class=_read_metadata(d).get("primary_class", "?"),
            )
        write_result(d, r)
        results.append(r)
        logger.info(
            "  %s grade=%s comps=%d cad=%s map=%.0f%%",
            r.patent_id, r.quality_grade, r.components_count,
            r.cad_generated, r.mapping_complete * 100
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claim2cad.validator")
    parser.add_argument("--patents-dir", type=Path, default=PATENTS_DIR)
    parser.add_argument("--limit", type=int, default=None,
                        help="Max patents to validate (default: all)")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    logging.getLogger("claim2cad").setLevel(logging.INFO)

    patent_dirs = sorted(d for d in args.patents_dir.iterdir()
                         if d.is_dir() and (d / "claim.txt").exists())
    if args.limit:
        patent_dirs = patent_dirs[: args.limit]
    logger.info("Validating %d patents", len(patent_dirs))

    pre_cost = cumulative_cost()
    results = run_batch(patent_dirs)
    post_cost = cumulative_cost()

    if args.report:
        write_validation_report(results, iteration=args.iteration,
                                extra_context=f"Cost delta this run: "
                                              f"${post_cost - pre_cost:.3f}")
    summary = cost_summary()
    print(json.dumps({
        "patents": len(results),
        "good": sum(1 for r in results if r.quality_grade == "good"),
        "partial": sum(1 for r in results if r.quality_grade == "partial"),
        "fail": sum(1 for r in results if r.quality_grade == "fail"),
        "cost_delta_usd": round(post_cost - pre_cost, 4),
        "cost_total_usd": summary["total_cost_usd"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
