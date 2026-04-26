"""Tests for the IR schema.

These exercises double as living documentation of the schema's invariants.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claim2cad.ir_schema import (
    Claim,
    ClaimIR,
    Component,
    Dimension,
    DimensionRelative,
    DimensionUnspecified,
    DimensionValue,
    Relation,
    SourceSpan,
    WhereinClause,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_IR_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "expected_ir.json"
GOLDEN_CLAIM_PATH = REPO_ROOT / "examples" / "golden_robot_arm" / "claim.txt"


def _minimal_claim_kwargs(claim_id: str = "claim_1") -> dict:
    return {"id": claim_id, "text": "An apparatus, comprising: a widget."}


def _minimal_span(claim_id: str = "claim_1") -> SourceSpan:
    return SourceSpan(claim_id=claim_id, char_start=0, char_end=5)


# ---------------------------------------------------------------------------
# Golden IR validates
# ---------------------------------------------------------------------------


def test_golden_expected_ir_validates() -> None:
    raw = GOLDEN_IR_PATH.read_text(encoding="utf-8")
    ir = ClaimIR.model_validate_json(raw)
    assert ir.title.strip()
    assert len(ir.claims) == 2
    assert len(ir.components) == 9
    assert len(ir.relations) == 8
    assert len(ir.wherein_clauses) == 2


def test_golden_spans_index_into_claim_text() -> None:
    """Every component's source_span must slice a non-empty substring of the
    referenced claim's text."""
    ir = ClaimIR.model_validate_json(GOLDEN_IR_PATH.read_text(encoding="utf-8"))
    by_id = {c.id: c.text for c in ir.claims}
    for comp in ir.components:
        body = by_id[comp.source_span.claim_id]
        slice_ = body[comp.source_span.char_start : comp.source_span.char_end]
        assert slice_.strip(), (
            f"component {comp.id} has empty source_span: "
            f"{comp.source_span}"
        )


def test_golden_independent_dependent_split() -> None:
    ir = ClaimIR.model_validate_json(GOLDEN_IR_PATH.read_text(encoding="utf-8"))
    independent = [c for c in ir.claims if c.is_independent]
    dependent = [c for c in ir.claims if not c.is_independent]
    assert len(independent) == 1 and independent[0].id == "claim_1"
    assert len(dependent) == 1 and dependent[0].depends_on == "claim_1"

    sensor = next(c for c in ir.components if c.id == "position_sensor")
    assert sensor.is_dependent is True
    assert sensor.dependent_on == "claim_1"
    assert sensor.source_span.claim_id == "claim_2"


# ---------------------------------------------------------------------------
# Schema-level validators
# ---------------------------------------------------------------------------


def test_dimension_discriminator_round_trip() -> None:
    cases: list[Dimension] = [
        DimensionUnspecified(),
        DimensionRelative(description="longer than the first link"),
        DimensionValue(value=30, unit="mm"),
    ]
    for original in cases:
        as_dict = original.model_dump()
        # Reparse via Component to exercise the discriminator
        comp = Component(
            id="x",
            label="X",
            category="structural",
            kind="rod",
            dimension=as_dict,
            source_span=_minimal_span(),
        )
        assert comp.dimension.kind == original.kind  # type: ignore[union-attr]


def test_source_span_must_be_non_inverted() -> None:
    with pytest.raises(ValidationError):
        SourceSpan(claim_id="claim_1", char_start=10, char_end=2)


def test_referential_integrity_unknown_parent_id() -> None:
    """Component.parent_id must point at another component."""
    span = _minimal_span()
    with pytest.raises(ValidationError):
        ClaimIR(
            title="T",
            claims=[Claim(**_minimal_claim_kwargs())],
            components=[
                Component(
                    id="orphan",
                    label="orphan",
                    category="structural",
                    kind="rod",
                    parent_id="ghost",
                    source_span=span,
                ),
            ],
        )


def test_referential_integrity_unknown_relation_endpoint() -> None:
    span = _minimal_span()
    with pytest.raises(ValidationError):
        ClaimIR(
            title="T",
            claims=[Claim(**_minimal_claim_kwargs())],
            components=[
                Component(
                    id="a",
                    label="a",
                    category="structural",
                    kind="rod",
                    source_span=span,
                ),
            ],
            relations=[
                Relation(
                    id="rel_a_b",
                    kind="attached_to",
                    source="a",
                    target="ghost",
                    source_span=span,
                ),
            ],
        )


def test_wherein_clause_must_target_known_id() -> None:
    span = _minimal_span()
    with pytest.raises(ValidationError):
        ClaimIR(
            title="T",
            claims=[Claim(**_minimal_claim_kwargs())],
            components=[
                Component(
                    id="a",
                    label="a",
                    category="structural",
                    kind="rod",
                    source_span=span,
                ),
            ],
            wherein_clauses=[
                WhereinClause(
                    id="w1",
                    text="wherein the bogus is bogus",
                    targets=["bogus"],
                    source_span=span,
                ),
            ],
        )


def test_component_id_pattern_rejects_uppercase() -> None:
    with pytest.raises(ValidationError):
        Component(
            id="FirstLink",
            label="first link",
            category="structural",
            kind="rod",
            source_span=_minimal_span(),
        )


def test_claim_id_pattern_enforced() -> None:
    with pytest.raises(ValidationError):
        Claim(id="claimOne", text="foo")


def test_round_trip_via_model_dump_json() -> None:
    raw = GOLDEN_IR_PATH.read_text(encoding="utf-8")
    ir = ClaimIR.model_validate_json(raw)
    dumped = ir.model_dump_json(indent=2)
    re_ir = ClaimIR.model_validate_json(dumped)
    assert re_ir == ir
