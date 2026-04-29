"""V11-37 — eval metrics for figure-hotspot grounding."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.eval_v11 import _eval_hotspot_grounding

REPO_ROOT = Path(__file__).resolve().parent.parent
US4807331A = REPO_ROOT / "examples/real_patents/US4807331A_spring_loaded_hinge"


@pytest.mark.skipif(
    not (US4807331A / "figure_hotspots.json").exists(),
    reason="figure_hotspots.json absent — run hotspot pipeline first",
)
def test_hotspot_grounding_returns_score() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    assert "score" in rep
    assert 0.0 <= rep["score"] <= 1.0


@pytest.mark.skipif(
    not (US4807331A / "leader_lines.json").exists(),
    reason="leader_lines.json absent",
)
def test_hotspot_grounding_leader_rate_above_floor() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    # Hough should pick up >= 80 % of US4807331A leaders. If this
    # regresses, leader_lines.py has been broken.
    assert rep["leader_line_detection_rate"] >= 0.80, rep


@pytest.mark.skipif(
    not (US4807331A / "figure_hotspots.json").exists(),
    reason="figure_hotspots.json absent",
)
def test_hotspot_grounding_part_hotspots_in_bounds() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    assert rep["out_of_bounds_count"] == 0


@pytest.mark.skipif(
    not (US4807331A / "figure_hotspots.json").exists(),
    reason="figure_hotspots.json absent",
)
def test_hotspot_grounding_preserves_repeated_instances() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    # US4807331A_spring_loaded_hinge has duplicate callouts at
    # upper + lower hinges; the V11-36 pipeline must keep at least
    # some of them as separate hotspot instances.
    if rep["duplicate_callout_numbers"] > 0:
        assert rep["repeated_instance_count"] > 0, rep


@pytest.mark.skipif(
    not (US4807331A / "figure_hotspots.json").exists(),
    reason="figure_hotspots.json absent",
)
def test_hotspot_grounding_emits_label_kind_too() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    # V11-35 emits a label hotspot per part hotspot. The counts
    # should match within ±1 (they may differ if a label fails to
    # bind to a component_id — exotic edge case).
    n_part = rep["n_part_hotspots"]
    n_label = rep["n_label_hotspots"]
    assert abs(n_part - n_label) <= 1, rep


@pytest.mark.skipif(
    not (US4807331A / "figure_hotspots.json").exists(),
    reason="figure_hotspots.json absent",
)
def test_hotspot_grounding_source_distribution_keys_valid() -> None:
    rep = _eval_hotspot_grounding(US4807331A)
    valid = {
        "leader_endpoint",
        "projection_anchor",
        "median_label",
        "label_center",
        "crop_center",
        "manual_override",
        "label",
        "figure_projection",  # legacy
        "unknown",
    }
    for src in rep["hotspot_source_distribution"]:
        assert src in valid, f"unexpected source: {src}"
