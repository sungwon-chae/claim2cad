"""V13-N — semantic mismatch detector tests."""
from __future__ import annotations

import json
from pathlib import Path

from claim2cad.semantic_mismatch import detect_one


def _setup_example(tmp_path: Path, ex_id: str,
                    *, classification: dict,
                    batch_status: dict | None = None,
                    claim_map: dict | None = None) -> Path:
    ex = tmp_path / ex_id
    ex.mkdir()
    (ex / "figure_classification.json").write_text(
        json.dumps(classification))
    if batch_status:
        (ex / "batch_status.json").write_text(json.dumps(batch_status))
    if claim_map:
        (ex / "claim_map.json").write_text(json.dumps(claim_map))
    return ex


def test_no_mismatch_when_topology_matches_id(tmp_path):
    ex = _setup_example(
        tmp_path, "US4807331A_spring_loaded_hinge",
        classification={"topology": "door_hinge",
                         "recommended_scaffold": "door_hinge"},
        batch_status={"scaffold_id": "door_hinge"},
    )
    rep = detect_one(ex)
    assert rep.has_mismatch is False
    assert rep.severity == "none"


def test_warning_when_id_clearly_disagrees(tmp_path):
    ex = _setup_example(
        tmp_path, "US5180955A_positioning_apparatus_for_arm",
        classification={"topology": "rotary_shaft",
                         "recommended_scaffold": "rotary_shaft"},
        batch_status={"scaffold_id": "rotary_shaft"},
    )
    rep = detect_one(ex)
    assert rep.has_mismatch is True
    assert rep.severity == "warning"
    assert "positioning_apparatus" in rep.expected_topologies


def test_advisory_for_close_neighbour(tmp_path):
    ex = _setup_example(
        tmp_path, "US3705522A_planetary_gear_with_idler",
        classification={"topology": "rotary_shaft",
                         "recommended_scaffold": "rotary_shaft"},
        batch_status={"scaffold_id": "rotary_shaft"},
    )
    rep = detect_one(ex)
    # planetary_gear is in name; rotary_shaft is a near-neighbour.
    assert rep.has_mismatch is True
    assert rep.severity in ("advisory", "warning")
    assert "planetary_gear" in rep.expected_topologies


def test_no_signal_returns_clean(tmp_path):
    ex = _setup_example(
        tmp_path, "patent_xyz",
        classification={"topology": "rotary_shaft"},
    )
    rep = detect_one(ex)
    assert rep.has_mismatch is False
    assert rep.expected_topologies == []


def test_corrected_planetary_is_clean(tmp_path):
    """After V13-K/L, a planetary_gear-named example whose
    classifier picked planetary_gear and built with the
    planetary_gear scaffold must NOT show a mismatch."""
    ex = _setup_example(
        tmp_path, "US3705522A_planetary_gear_with_idler",
        classification={"topology": "planetary_gear",
                         "recommended_scaffold": "planetary_gear"},
        batch_status={"scaffold_id": "planetary_gear"},
    )
    rep = detect_one(ex)
    assert rep.has_mismatch is False
    assert rep.severity == "none"
