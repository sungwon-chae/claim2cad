"""Tests for V1-11 evaluation harness."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.eval_harness import (
    DEFAULT_BENCHMARK,
    EvalReport,
    ExampleResult,
    PRMetric,
    evaluate_all,
    evaluate_example,
    format_report_json,
    format_report_md,
)
from claim2cad.ir_schema import (
    Claim,
    ClaimIR,
    Component,
    Relation,
    SourceSpan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "examples" / "golden_robot_arm"
KOREAN_DIR = REPO_ROOT / "examples" / "korean_robot_arm"
DRONE_DIR = REPO_ROOT / "examples" / "multi_claim_drone"


# ---------------------------------------------------------------------------
# PRMetric arithmetic
# ---------------------------------------------------------------------------


def test_pr_metric_perfect_match() -> None:
    pr = PRMetric(tp=5, fp=0, fn=0)
    assert pr.precision == 1.0
    assert pr.recall == 1.0
    assert pr.f1 == 1.0


def test_pr_metric_with_misses() -> None:
    pr = PRMetric(tp=3, fp=2, fn=1)
    assert pr.precision == pytest.approx(3 / 5)
    assert pr.recall == pytest.approx(3 / 4)
    assert pr.f1 > 0


def test_pr_metric_empty_returns_unit() -> None:
    """No predictions and no truths is a degenerate but valid scenario."""
    pr = PRMetric(tp=0, fp=0, fn=0)
    assert pr.recall == 1.0  # nothing to find, found nothing


def test_pr_metric_add() -> None:
    a = PRMetric(tp=2, fp=1, fn=1)
    b = PRMetric(tp=3, fp=0, fn=2)
    c = a.add(b)
    assert c.tp == 5
    assert c.fp == 1
    assert c.fn == 3


# ---------------------------------------------------------------------------
# Single-example evaluation
# ---------------------------------------------------------------------------


def test_evaluate_example_dryrun_self_consistent() -> None:
    """Dry-run mode replays expected_ir.json — every metric should be ~1.0."""
    result = evaluate_example(GOLDEN_DIR, mode="dryrun")
    assert result.error is None
    assert result.expected_components == result.actual_components
    assert result.component_kinds.f1 == 1.0
    assert result.component_ids.f1 == 1.0
    assert result.relation_triples.f1 == 1.0
    assert result.cad_step_ok is True
    assert result.cad_glb_ok is True
    assert result.span_coverage == 1.0


def test_evaluate_example_korean_dryrun() -> None:
    result = evaluate_example(KOREAN_DIR, mode="dryrun")
    assert result.error is None
    assert result.expected_components == 6
    assert result.cad_step_ok is True


def test_evaluate_example_drone_dryrun() -> None:
    result = evaluate_example(DRONE_DIR, mode="dryrun")
    assert result.error is None
    assert result.claim_count == 5
    assert result.expected_components == 17


def test_evaluate_example_missing_files_records_error(tmp_path: Path) -> None:
    """A directory with no claim.txt should not crash."""
    result = evaluate_example(tmp_path, mode="dryrun")
    assert result.error is not None
    assert "missing" in result.error.lower()


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def test_evaluate_all_default_benchmark_runs() -> None:
    report = evaluate_all(DEFAULT_BENCHMARK, mode="dryrun")
    assert report.n_evaluated == len(DEFAULT_BENCHMARK)
    assert report.cad_success_rate() == 1.0
    assert report.aggregate_pr("component_kinds").f1 == 1.0


def test_evaluate_all_handles_missing_dir(tmp_path: Path) -> None:
    """One missing directory shouldn't fail the whole batch."""
    report = evaluate_all([tmp_path, GOLDEN_DIR], mode="dryrun")
    assert report.n_evaluated == 1
    bad = next(e for e in report.examples if e.error is not None)
    assert bad.error is not None


# ---------------------------------------------------------------------------
# Stub mode produces non-trivial numbers
# ---------------------------------------------------------------------------


def test_stub_mode_grades_drone_below_perfect(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deterministic stub parser is NOT expected to match the
    LLM-quality expected_ir.json on a 5-claim hierarchy. The harness
    should report a sub-perfect score, proving it actually evaluates the
    parser rather than rubber-stamping the input."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = evaluate_example(DRONE_DIR, mode="stub")
    assert result.error is None
    # Stub will overcount or undercount; the F1 must be < 1.0 to prove
    # the harness is doing real work.
    assert result.component_kinds.f1 < 1.0
    assert result.relation_triples.f1 < 1.0


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def test_format_report_json_is_valid_json() -> None:
    report = evaluate_all([GOLDEN_DIR, KOREAN_DIR], mode="dryrun")
    blob = format_report_json(report)
    payload = json.loads(blob)
    assert "summary" in payload
    assert "examples" in payload
    assert payload["summary"]["n_evaluated"] == 2
    # Each example carries the PR breakdown as nested objects.
    for entry in payload["examples"]:
        for metric in ("component_ids", "component_kinds", "relation_triples"):
            assert "precision" in entry[metric]
            assert "f1" in entry[metric]


def test_format_report_md_includes_per_example_table() -> None:
    report = evaluate_all([GOLDEN_DIR, KOREAN_DIR], mode="dryrun")
    md = format_report_md(report)
    assert "# Claim2CAD evaluation report" in md
    assert "Per-example breakdown" in md
    assert "golden_robot_arm" in md
    assert "korean_robot_arm" in md
    assert "kind_F1" in md  # column header


def test_default_benchmark_meets_brief_coverage() -> None:
    """Brief: 'one golden, one Korean, one multi-claim'."""
    names = [d.name for d in DEFAULT_BENCHMARK]
    assert "golden_robot_arm" in names
    assert "korean_robot_arm" in names
    assert "multi_claim_drone" in names
