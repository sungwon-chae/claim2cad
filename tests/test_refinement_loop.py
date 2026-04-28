"""Tests for claim2cad.refinement_loop deterministic helpers.

Live VLM behaviour (iterative refinement) is exercised manually via the
CLI; the tests here cover the bits that have to keep working regardless
of model behaviour: defect-driven component selection, severity ordering,
spec merging, and stop-reason logic.
"""
from __future__ import annotations

import pytest

from claim2cad.figure_to_cad import ComponentSpec, FigureSpec
from claim2cad.refinement_loop import (
    IterationRecord,
    _merge_revisions,
    _pick_components_to_refine,
    _stop_reason,
)
from claim2cad.visual_validator import SimilarityReport


def _spec(*ids: str) -> FigureSpec:
    return FigureSpec(
        patent_id="t",
        figure_id="figure_1",
        components=[ComponentSpec(component_id=i, library_part="plate") for i in ids],
    )


def test_pick_components_orders_by_severity() -> None:
    spec = _spec("a", "b", "c", "d")
    report = SimilarityReport(
        defects=[
            {"component": "a", "issue": "x", "severity": "minor"},
            {"component": "b", "issue": "x", "severity": "major"},
            {"component": "c", "issue": "x", "severity": "moderate"},
            {"component": "d", "issue": "x", "severity": "major"},
        ]
    )
    picked = [s.component_id for s in _pick_components_to_refine(report, spec, max_components=3)]
    # b and d (major) come first, then c (moderate). a (minor) capped out.
    assert picked == ["b", "d", "c"]


def test_pick_components_dedupes_repeated_ids() -> None:
    spec = _spec("a")
    report = SimilarityReport(
        defects=[
            {"component": "a", "issue": "size", "severity": "major"},
            {"component": "a", "issue": "rotation", "severity": "moderate"},
        ]
    )
    picked = _pick_components_to_refine(report, spec)
    assert [s.component_id for s in picked] == ["a"]


def test_pick_components_skips_unknown_ids() -> None:
    spec = _spec("a")
    report = SimilarityReport(
        defects=[
            {"component": "ghost", "issue": "x", "severity": "major"},
            {"component": "a", "issue": "x", "severity": "minor"},
        ]
    )
    picked = [s.component_id for s in _pick_components_to_refine(report, spec)]
    assert picked == ["a"]


def test_merge_revisions_overrides_only_supplied_ids() -> None:
    spec = _spec("a", "b", "c")
    revisions = [
        ComponentSpec(component_id="b", library_part="rod", position_mm=(10.0, 0.0, 0.0)),
    ]
    merged = _merge_revisions(spec, revisions)
    by_id = {s.component_id: s for s in merged.components}
    assert by_id["a"].library_part == "plate"
    assert by_id["b"].library_part == "rod"
    assert by_id["b"].position_mm == (10.0, 0.0, 0.0)
    assert by_id["c"].library_part == "plate"


def test_stop_reason_target_reached() -> None:
    h = [IterationRecord(iteration=0, score=8.0)]
    assert "target_score" in _stop_reason(h, target_score=8.0, max_iterations=3, cost_soft_cap=70.0)


def test_stop_reason_cost_cap() -> None:
    h = [IterationRecord(iteration=0, score=2.0, cost_usd_so_far=99.0)]
    assert "cost_soft_cap" in _stop_reason(h, target_score=8.0, max_iterations=3, cost_soft_cap=70.0)


def test_stop_reason_no_improvement() -> None:
    h = [
        IterationRecord(iteration=0, score=4.0),
        IterationRecord(iteration=1, score=3.0),
        IterationRecord(iteration=2, score=3.0),
    ]
    assert "improvement" in _stop_reason(h, target_score=8.0, max_iterations=5, cost_soft_cap=70.0)


def test_iteration_record_as_row_includes_key_fields() -> None:
    r = IterationRecord(
        iteration=2,
        score=5.5,
        silhouette=6.0,
        proportion=5.0,
        feature=5.0,
        arrangement=6.0,
        defect_count=3,
        refined_components=["a", "b"],
        cost_usd_so_far=1.234,
    )
    s = r.as_row()
    assert "02" in s
    assert "5.5" in s
    assert "defects=3" in s
    assert "a,b" in s
    assert "$1.234" in s
