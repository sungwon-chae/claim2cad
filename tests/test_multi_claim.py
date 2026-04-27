"""Tests for V1-8 multi-claim hierarchy support."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.claim_hierarchy import (
    claim_chain,
    components_for_claim,
    filter_ir_to_claim,
    hierarchy_summary,
)
from claim2cad.ir_schema import ClaimIR

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_IR = REPO_ROOT / "examples" / "golden_robot_arm" / "expected_ir.json"
DRONE_DIR = REPO_ROOT / "examples" / "multi_claim_drone"
DRONE_IR = DRONE_DIR / "expected_ir.json"


def _golden_ir() -> ClaimIR:
    return ClaimIR.model_validate_json(GOLDEN_IR.read_text(encoding="utf-8"))


def _drone_ir() -> ClaimIR:
    return ClaimIR.model_validate_json(DRONE_IR.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# claim_chain
# ---------------------------------------------------------------------------


def test_claim_chain_independent_claim_returns_singleton() -> None:
    ir = _golden_ir()
    assert claim_chain(ir, "claim_1") == ["claim_1"]


def test_claim_chain_walks_one_level() -> None:
    ir = _golden_ir()
    assert claim_chain(ir, "claim_2") == ["claim_2", "claim_1"]


def test_claim_chain_walks_deep_hierarchy() -> None:
    ir = _drone_ir()
    # claim_5 → claim_4 → claim_3 → claim_1 (depth 4)
    chain = claim_chain(ir, "claim_5")
    assert chain == ["claim_5", "claim_4", "claim_3", "claim_1"]


def test_claim_chain_unknown_claim_raises() -> None:
    ir = _golden_ir()
    with pytest.raises(KeyError):
        claim_chain(ir, "claim_42")


# ---------------------------------------------------------------------------
# components_for_claim
# ---------------------------------------------------------------------------


def test_components_for_claim_with_ancestors_includes_parent_components() -> None:
    ir = _golden_ir()
    comps = components_for_claim(ir, "claim_2", include_ancestors=True)
    ids = {c.id for c in comps}
    assert "position_sensor" in ids  # claim_2 contribution
    assert "second_link" in ids       # claim_1 contribution


def test_components_for_claim_without_ancestors_isolates_contribution() -> None:
    ir = _golden_ir()
    comps = components_for_claim(ir, "claim_2", include_ancestors=False)
    assert [c.id for c in comps] == ["position_sensor"]


def test_components_for_claim_drone_branch_excludes_unrelated_branches() -> None:
    ir = _drone_ir()
    # claim_5 inherits from claim_4 → claim_3 → claim_1, so the battery
    # (introduced by claim_2 only) must NOT be in the chain.
    comps_5 = components_for_claim(ir, "claim_5", include_ancestors=True)
    ids = {c.id for c in comps_5}
    assert "battery" not in ids
    assert "camera" in ids
    assert "position_sensor" in ids
    assert "flight_controller" in ids
    assert "frame" in ids


# ---------------------------------------------------------------------------
# filter_ir_to_claim
# ---------------------------------------------------------------------------


def test_filter_ir_to_claim_returns_valid_ir() -> None:
    ir = _drone_ir()
    filtered = filter_ir_to_claim(ir, "claim_2")
    # Validation runs in ClaimIR.__init__; if we got here, it's valid.
    assert filtered.title == ir.title
    assert {c.id for c in filtered.claims} == {"claim_1", "claim_2"}


def test_filter_ir_to_claim_drops_relations_with_orphan_endpoints() -> None:
    """A relation whose target is in a filtered-out claim must be dropped."""
    ir = _drone_ir()
    filtered = filter_ir_to_claim(ir, "claim_2")
    component_ids = {c.id for c in filtered.components}
    for rel in filtered.relations:
        assert rel.source in component_ids
        assert rel.target in component_ids
        if rel.via is not None:
            assert rel.via in component_ids


def test_filter_ir_to_claim_alone_keeps_only_named_claim() -> None:
    ir = _golden_ir()
    filtered = filter_ir_to_claim(ir, "claim_2", include_ancestors=False)
    assert [c.id for c in filtered.claims] == ["claim_2"]
    assert [c.id for c in filtered.components] == ["position_sensor"]


def test_filter_ir_to_claim_deep_chain_skips_sibling_claims() -> None:
    ir = _drone_ir()
    filtered = filter_ir_to_claim(ir, "claim_5")
    assert {c.id for c in filtered.claims} == {
        "claim_1", "claim_3", "claim_4", "claim_5",
    }
    # Battery is from claim_2 which is a sibling — should NOT be present.
    component_ids = {c.id for c in filtered.components}
    assert "battery" not in component_ids
    assert "camera" in component_ids


# ---------------------------------------------------------------------------
# hierarchy_summary
# ---------------------------------------------------------------------------


def test_hierarchy_summary_drone_shape() -> None:
    ir = _drone_ir()
    summary = hierarchy_summary(ir)
    assert summary["n_independent"] == 1
    assert summary["n_dependent"] == 4
    assert summary["max_depth"] == 4
    assert len(summary["claims"]) == 5
    by_id = {c["id"]: c for c in summary["claims"]}
    assert by_id["claim_1"]["n_components_introduced"] >= 5
    assert by_id["claim_2"]["depends_on"] == "claim_1"
    assert by_id["claim_5"]["chain"] == [
        "claim_5", "claim_4", "claim_3", "claim_1",
    ]


def test_hierarchy_summary_round_trips_to_json() -> None:
    ir = _drone_ir()
    summary = hierarchy_summary(ir)
    blob = json.dumps(summary)
    assert "claim_5" in blob


def test_drone_claim_hierarchy_file_matches_summary() -> None:
    ir = _drone_ir()
    expected = hierarchy_summary(ir)
    on_disk = json.loads(
        (DRONE_DIR / "claim_hierarchy.json").read_text(encoding="utf-8")
    )
    assert on_disk["n_independent"] == expected["n_independent"]
    assert on_disk["n_dependent"] == expected["n_dependent"]
    assert on_disk["max_depth"] == expected["max_depth"]


# ---------------------------------------------------------------------------
# CLI / pipeline integration
# ---------------------------------------------------------------------------


def test_pipeline_emits_claim_hierarchy_json(tmp_path: Path) -> None:
    from claim2cad.pipeline import run_pipeline

    artifacts = run_pipeline(
        claim_path=DRONE_DIR / "claim.txt",
        out_dir=tmp_path,
        dry_run=True,
        write_generator=False,
    )
    assert "claim_hierarchy" in artifacts
    summary = json.loads(artifacts["claim_hierarchy"].read_text(encoding="utf-8"))
    assert summary["max_depth"] == 4
    assert summary["n_dependent"] == 4


def test_pipeline_filter_claim_reduces_components(tmp_path: Path) -> None:
    from claim2cad.pipeline import run_pipeline

    artifacts = run_pipeline(
        claim_path=DRONE_DIR / "claim.txt",
        out_dir=tmp_path,
        dry_run=True,
        write_generator=False,
        filter_claim="2",
    )
    ir = ClaimIR.model_validate_json(artifacts["claim_ir"].read_text("utf-8"))
    component_ids = {c.id for c in ir.components}
    assert "battery" in component_ids
    assert "camera" not in component_ids
    assert "position_sensor" not in component_ids
    # Both claim_1 and claim_2 should be present.
    assert {c.id for c in ir.claims} == {"claim_1", "claim_2"}


def test_pipeline_filter_claim_with_explicit_prefix(tmp_path: Path) -> None:
    """Both '2' and 'claim_2' should be accepted."""
    from claim2cad.pipeline import run_pipeline

    artifacts = run_pipeline(
        claim_path=DRONE_DIR / "claim.txt",
        out_dir=tmp_path,
        dry_run=True,
        write_generator=False,
        filter_claim="claim_2",
    )
    ir = ClaimIR.model_validate_json(artifacts["claim_ir"].read_text("utf-8"))
    assert {c.id for c in ir.claims} == {"claim_1", "claim_2"}
