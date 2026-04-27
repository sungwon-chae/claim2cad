"""Tests for the claim parser.

The parser has three branches:

1. Golden short-circuit (text matches the canonical golden claim).
2. LLM path (mocked here — we don't depend on a network or API key).
3. Rule-based stub fallback (the path our hinge example exercises by default).

Tests assert *structural* properties (component counts, kind distribution,
provenance integrity) rather than exact equality, per the Phase-4 brief.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claim2cad.claim_parser import parse_claim
from claim2cad.claim_segmenter import segment_claim
from claim2cad.ir_schema import ClaimIR

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_CLAIM = REPO_ROOT / "examples" / "golden_robot_arm" / "claim.txt"
GOLDEN_IR = REPO_ROOT / "examples" / "golden_robot_arm" / "expected_ir.json"
HINGE_CLAIM = REPO_ROOT / "examples" / "hinge_assembly" / "claim.txt"


def _all_components_have_provenance(ir: ClaimIR) -> bool:
    claim_ids = {c.id for c in ir.claims}
    for comp in ir.components:
        if comp.source_span.claim_id not in claim_ids:
            return False
        if comp.source_span.char_end <= comp.source_span.char_start:
            return False
    return True


# ---------------------------------------------------------------------------
# Golden short-circuit
# ---------------------------------------------------------------------------


def test_golden_short_circuit_returns_canonical_ir() -> None:
    text = GOLDEN_CLAIM.read_text(encoding="utf-8")
    ir = parse_claim(text)
    assert ir.title == "Articulated robotic manipulator"
    assert len(ir.components) == 9
    revolute = [c for c in ir.components if c.kind == "revolute_joint"]
    assert len(revolute) == 2
    assert any(c.is_dependent for c in ir.components)
    assert _all_components_have_provenance(ir)


# ---------------------------------------------------------------------------
# Hinge — exercises the rule-based stub
# ---------------------------------------------------------------------------


def test_hinge_stub_extracts_links_and_joints() -> None:
    text = HINGE_CLAIM.read_text(encoding="utf-8")
    # No env key in CI → the stub path runs.
    ir = parse_claim(text)
    assert len(ir.components) >= 4, f"expected ≥4 components, got {len(ir.components)}"
    revolute = [c for c in ir.components if c.kind == "revolute_joint"]
    assert revolute, "expected at least 1 revolute_joint"
    rods = [c for c in ir.components if c.kind == "rod"]
    assert len(rods) >= 4, f"expected ≥4 rods (links), got {len(rods)}"
    assert _all_components_have_provenance(ir)


def test_hinge_segmenter_finds_one_independent_claim() -> None:
    text = HINGE_CLAIM.read_text(encoding="utf-8")
    segments = segment_claim(text)
    assert len(segments) == 1
    assert segments[0].is_independent is True
    assert len(segments[0].elements) >= 4
    assert len(segments[0].wherein_clauses) >= 1


# ---------------------------------------------------------------------------
# Synthetic edge case — completely empty / unrecognised claim
# ---------------------------------------------------------------------------


def test_empty_claim_returns_stub_with_one_component() -> None:
    ir = parse_claim("   ")
    assert len(ir.claims) == 1
    assert len(ir.components) == 1
    assert _all_components_have_provenance(ir)


def test_minimal_claim_returns_at_least_one_component() -> None:
    ir = parse_claim("1. A widget.")
    assert len(ir.components) >= 1
    assert _all_components_have_provenance(ir)


# ---------------------------------------------------------------------------
# LLM path — fully mocked
# ---------------------------------------------------------------------------


def _mock_llm_response_for(text: str) -> dict:
    """Return a minimally-valid IR payload referencing `text`."""
    return {
        "schema_version": "0.1.0",
        "title": "Mocked apparatus",
        "claims": [
            {
                "id": "claim_1",
                "text": text.strip(),
                "is_independent": True,
                "depends_on": None,
            }
        ],
        "components": [
            {
                "id": "widget",
                "label": "widget",
                "category": "structural",
                "kind": "block",
                "parent_id": None,
                "dimension": {"kind": "unspecified"},
                "constraints": [],
                "source_span": {
                    "claim_id": "claim_1",
                    "char_start": 0,
                    "char_end": min(len(text.strip()), 8),
                },
                "is_dependent": False,
                "dependent_on": None,
            },
            {
                "id": "joint",
                "label": "joint",
                "category": "connection",
                "kind": "revolute_joint",
                "parent_id": None,
                "dimension": {"kind": "unspecified"},
                "constraints": [],
                "source_span": {
                    "claim_id": "claim_1",
                    "char_start": 0,
                    "char_end": min(len(text.strip()), 8),
                },
                "is_dependent": False,
                "dependent_on": None,
            },
        ],
        "relations": [],
        "wherein_clauses": [],
    }


def test_llm_path_succeeds_with_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "1. A novel widget, comprising: a thingamajig connected to a doohickey."
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch(
        "claim2cad.claim_parser.json_completion",
        return_value=_mock_llm_response_for(text),
    ):
        ir = parse_claim(text)
    assert ir.title == "Mocked apparatus"
    assert len(ir.components) == 2
    assert any(c.kind == "revolute_joint" for c in ir.components)


def test_llm_path_retries_on_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """First response is invalid; second is valid → parser succeeds."""
    text = "1. A novel widget, comprising: a thingamajig."
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    bad = {"foo": "bar"}  # fails schema validation
    good = _mock_llm_response_for(text)
    with patch(
        "claim2cad.claim_parser.json_completion",
        side_effect=[bad, good],
    ) as mock_fn:
        ir = parse_claim(text)
    assert mock_fn.call_count == 2
    assert ir.title == "Mocked apparatus"


def test_llm_path_falls_back_to_stub_on_persistent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "1. A foo, comprising: a bar; a baz."
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch(
        "claim2cad.claim_parser.json_completion",
        side_effect=[{"bad": "data"}, {"also": "bad"}],
    ):
        ir = parse_claim(text)
    # Falls back to the rule-based stub. The text has 2 elements so we
    # expect 2 stub components.
    assert len(ir.components) >= 2
    assert _all_components_have_provenance(ir)
