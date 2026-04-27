"""Tests for V1-9 dimension extraction."""
from __future__ import annotations

import pytest

from claim2cad.dimension_extractor import extract_dimension
from claim2cad.ir_schema import (
    DimensionRelative,
    DimensionUnspecified,
    DimensionValue,
)


# ---------------------------------------------------------------------------
# English — explicit values
# ---------------------------------------------------------------------------


def test_explicit_value_simple() -> None:
    dim, qual = extract_dimension("a shaft of length 30 mm")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 30.0
    assert dim.unit == "mm"
    assert qual is None


def test_explicit_value_decimal_no_space() -> None:
    dim, qual = extract_dimension("a bore of diameter 12.5mm")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 12.5
    assert dim.unit == "mm"


def test_explicit_value_inches() -> None:
    dim, qual = extract_dimension("a stroke of 0.5 inches")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 0.5
    assert dim.unit == "in"


def test_explicit_value_meter_normalised() -> None:
    dim, qual = extract_dimension("a beam approximately 2 meters long")
    # The "approximately" pattern wins; qualifier must reflect that.
    assert isinstance(dim, DimensionValue)
    assert dim.value == 2.0
    assert dim.unit == "m"
    assert qual == "approximate"


def test_word_unit_handled() -> None:
    dim, _ = extract_dimension("the sleeve has a length of 10 millimeters")
    assert isinstance(dim, DimensionValue)
    assert dim.unit == "mm"


# ---------------------------------------------------------------------------
# English — qualifiers
# ---------------------------------------------------------------------------


def test_range_takes_midpoint_and_records_qualifier() -> None:
    dim, qual = extract_dimension("a link between 100 and 200 mm in length")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 150.0
    assert dim.unit == "mm"
    assert qual is not None and qual.startswith("range:")


def test_range_dash_separator() -> None:
    dim, qual = extract_dimension("a slot 5-15 mm wide")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 10.0
    assert qual is not None and qual.startswith("range:")


def test_at_least_qualifier() -> None:
    dim, qual = extract_dimension("a wall thickness of at least 3 mm")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 3.0
    assert qual == "minimum"


def test_no_more_than_qualifier() -> None:
    dim, qual = extract_dimension("a clearance no more than 0.2 mm")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 0.2
    assert qual == "maximum"


# ---------------------------------------------------------------------------
# English — comparative
# ---------------------------------------------------------------------------


def test_comparative_longer_than() -> None:
    dim, qual = extract_dimension("a second link longer than the first link")
    assert isinstance(dim, DimensionRelative)
    assert "longer than" in dim.description
    assert qual == "comparative"


def test_comparative_twice_length() -> None:
    dim, qual = extract_dimension("a beam twice the length of the base")
    assert isinstance(dim, DimensionRelative)
    assert "twice" in dim.description
    assert qual == "comparative"


# ---------------------------------------------------------------------------
# English — missing / ambiguous
# ---------------------------------------------------------------------------


def test_missing_dimension_returns_unspecified() -> None:
    dim, qual = extract_dimension("a base supporting the apparatus")
    assert isinstance(dim, DimensionUnspecified)
    assert qual is None


def test_empty_string_unspecified() -> None:
    dim, qual = extract_dimension("")
    assert isinstance(dim, DimensionUnspecified)
    assert qual is None


def test_ambiguous_no_unit_returns_unspecified() -> None:
    """Numbers without units (e.g. count words like '30 components') do not
    produce a DimensionValue."""
    dim, qual = extract_dimension("comprising 30 components")
    assert isinstance(dim, DimensionUnspecified)


# ---------------------------------------------------------------------------
# Korean
# ---------------------------------------------------------------------------


def test_korean_explicit_value_mm() -> None:
    dim, qual = extract_dimension("길이 30 mm 의 샤프트", language="ko")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 30.0
    assert dim.unit == "mm"


def test_korean_approximate() -> None:
    dim, qual = extract_dimension("약 50 cm의 길이를 갖는 링크", language="ko")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 50.0
    assert dim.unit == "cm"
    assert qual == "approximate"


def test_korean_range_naeji() -> None:
    dim, qual = extract_dimension("두께 5 내지 10 mm 의 플레이트", language="ko")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 7.5
    assert dim.unit == "mm"
    assert qual is not None and qual.startswith("range:")


def test_korean_at_least() -> None:
    dim, qual = extract_dimension("두께 3 mm 이상의 벽", language="ko")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 3.0
    assert dim.unit == "mm"
    assert qual == "minimum"


def test_korean_at_most() -> None:
    dim, qual = extract_dimension("간격이 0.5 mm 이하", language="ko")
    assert isinstance(dim, DimensionValue)
    assert dim.value == 0.5
    assert qual == "maximum"


def test_korean_comparative() -> None:
    dim, qual = extract_dimension("제1 링크보다 더 긴 제2 링크", language="ko")
    assert isinstance(dim, DimensionRelative)
    assert qual == "comparative"


def test_korean_missing_dimension() -> None:
    dim, qual = extract_dimension("베이스에 결합된 링크", language="ko")
    assert isinstance(dim, DimensionUnspecified)
    assert qual is None


# ---------------------------------------------------------------------------
# Integration with the parser stub path
# ---------------------------------------------------------------------------


def test_stub_parser_picks_up_explicit_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stub parser should populate dimensions when the claim text
    contains them — no LLM required."""
    from claim2cad.claim_parser import parse_claim

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = (
        "1. An apparatus, comprising: a base; a shaft of length 30 mm; "
        "and a sleeve approximately 5 mm in diameter."
    )
    ir = parse_claim(text)
    by_id = {c.id: c for c in ir.components}

    shaft = next(c for c in ir.components if "shaft" in c.id)
    assert isinstance(shaft.dimension, DimensionValue)
    assert shaft.dimension.value == 30.0
    assert shaft.dimension.unit == "mm"

    sleeve = next(c for c in ir.components if "sleeve" in c.id)
    assert isinstance(sleeve.dimension, DimensionValue)
    assert sleeve.dimension.value == 5.0
    assert "dimension:approximate" in sleeve.constraints

    base = by_id.get("base")
    assert base is not None
    # No dimension in claim text → unspecified.
    assert isinstance(base.dimension, DimensionUnspecified)


def test_stub_parser_korean_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    from claim2cad.claim_parser import parse_claim

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = (
        "베이스; 길이 50 mm 의 제1 링크; 두께 5 내지 10 mm 의 플레이트;"
        "를 포함하는 장치."
    )
    ir = parse_claim(text)
    # Find the link component.
    link = next(c for c in ir.components if c.id.startswith("first_link") or c.id == "link")
    assert isinstance(link.dimension, DimensionValue)
    assert link.dimension.value == 50.0
    assert link.dimension.unit == "mm"

    plate = next(c for c in ir.components if c.id == "plate")
    assert isinstance(plate.dimension, DimensionValue)
    assert plate.dimension.value == 7.5
    assert any(c.startswith("dimension:range") for c in plate.constraints)


def test_stub_parser_preserves_uncertainty_qualifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The qualifier ('approximate', 'range:...', 'minimum') must end up in
    constraints so the round-trip is loss-less."""
    from claim2cad.claim_parser import parse_claim

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = (
        "1. An apparatus, comprising: "
        "a frame; "
        "a sleeve at least 5 mm thick; "
        "a coupling between 10 and 20 mm long."
    )
    ir = parse_claim(text)
    sleeve = next(c for c in ir.components if "sleeve" in c.id)
    assert "dimension:minimum" in sleeve.constraints

    coupling = next(c for c in ir.components if "coupling" in c.id)
    assert any(c.startswith("dimension:range") for c in coupling.constraints)


# ---------------------------------------------------------------------------
# Backfill on LLM IR
# ---------------------------------------------------------------------------


def test_backfill_dimensions_overrides_unspecified() -> None:
    """If the LLM emits unspecified for a component whose source-span text
    contains an explicit dimension, the post-processor fills it in."""
    from claim2cad.claim_parser import _backfill_dimensions
    from claim2cad.ir_schema import (
        Claim,
        ClaimIR,
        Component,
        SourceSpan,
    )

    claim_text = "1. A foo, comprising: a shaft of length 25 mm; and a base."
    ir = ClaimIR(
        title="Foo",
        claims=[Claim(id="claim_1", text=claim_text, is_independent=True)],
        components=[
            Component(
                id="shaft",
                label="shaft",
                category="structural",
                kind="rod",
                source_span=SourceSpan(
                    claim_id="claim_1",
                    # Slice points at the ``shaft of length 25 mm`` substring.
                    char_start=claim_text.index("a shaft"),
                    char_end=claim_text.index(";"),
                ),
            ),
            Component(
                id="base",
                label="base",
                category="structural",
                kind="frame",
                source_span=SourceSpan(
                    claim_id="claim_1",
                    char_start=claim_text.index("a base"),
                    char_end=len(claim_text) - 1,
                ),
            ),
        ],
    )
    out = _backfill_dimensions(ir)
    by_id = {c.id: c for c in out.components}
    assert isinstance(by_id["shaft"].dimension, DimensionValue)
    assert by_id["shaft"].dimension.value == 25.0
    # Base has no dimension in its span text → still unspecified.
    assert isinstance(by_id["base"].dimension, DimensionUnspecified)


def test_backfill_dimensions_preserves_llm_dimensions() -> None:
    """LLM-set dimensions must survive backfill untouched."""
    from claim2cad.claim_parser import _backfill_dimensions
    from claim2cad.ir_schema import Claim, ClaimIR, Component, SourceSpan

    claim_text = "1. A foo, comprising: a shaft of length 25 mm."
    ir = ClaimIR(
        title="Foo",
        claims=[Claim(id="claim_1", text=claim_text, is_independent=True)],
        components=[
            Component(
                id="shaft",
                label="shaft",
                category="structural",
                kind="rod",
                dimension=DimensionValue(value=99.0, unit="cm"),
                source_span=SourceSpan(
                    claim_id="claim_1", char_start=0, char_end=20
                ),
            ),
        ],
    )
    out = _backfill_dimensions(ir)
    shaft = out.components[0]
    # 99 cm preserved (LLM-provided), even though "25 mm" appears in span text.
    assert shaft.dimension.value == 99.0
    assert shaft.dimension.unit == "cm"
