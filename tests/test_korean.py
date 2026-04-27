"""Tests for V1-7 Korean claim support.

These tests exercise:

1. Language detection (``claim2cad.lang.detect_language``).
2. Korean segmenter (claim split, dependent detection, preamble at the
   *end* rather than the start, element splitting on ``;``).
3. Korean stub-IR generation (head-noun extraction at end of clause,
   romanised IDs, kind classification on Korean head nouns).
4. End-to-end pipeline through the dry-run path (no LLM required).

The Korean example lives at ``examples/korean_robot_arm/``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claim2cad.claim_parser import parse_claim
from claim2cad.claim_segmenter import segment_claim
from claim2cad.ir_schema import ClaimIR
from claim2cad.lang import detect_language

REPO_ROOT = Path(__file__).resolve().parent.parent
KO_CLAIM = REPO_ROOT / "examples" / "korean_robot_arm" / "claim.txt"
KO_EXPECTED_IR = REPO_ROOT / "examples" / "korean_robot_arm" / "expected_ir.json"


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_detect_language_korean_claim() -> None:
    text = KO_CLAIM.read_text(encoding="utf-8")
    assert detect_language(text) == "ko"


def test_detect_language_english_claim() -> None:
    assert detect_language("1. A widget, comprising: a frob.") == "en"


def test_detect_language_empty_string_defaults_english() -> None:
    assert detect_language("") == "en"
    assert detect_language("   \n\n  ") == "en"


def test_detect_language_mixed_korean_english_uses_threshold() -> None:
    # Mostly English with one Korean word — should stay "en".
    text = "A first 링크 connected to a base."
    assert detect_language(text) == "en"
    # Mostly Korean with English part numbers — should be "ko".
    text2 = "베이스에 결합된 제1 링크 (10) 및 제2 링크 (20)."
    assert detect_language(text2) == "ko"


# ---------------------------------------------------------------------------
# Segmenter
# ---------------------------------------------------------------------------


def test_korean_segmenter_finds_two_claims() -> None:
    text = KO_CLAIM.read_text(encoding="utf-8")
    segs = segment_claim(text)
    assert len(segs) == 2, [s.claim_id for s in segs]
    assert segs[0].claim_id == "claim_1"
    assert segs[1].claim_id == "claim_2"
    assert all(s.language == "ko" for s in segs)


def test_korean_segmenter_independent_dependent_split() -> None:
    text = KO_CLAIM.read_text(encoding="utf-8")
    segs = segment_claim(text)
    assert segs[0].is_independent is True
    assert segs[0].depends_on is None
    assert segs[1].is_independent is False
    assert segs[1].depends_on == "claim_1"


def test_korean_segmenter_preamble_at_end() -> None:
    """Korean claims put the preamble noun at the *end* of the claim."""
    text = KO_CLAIM.read_text(encoding="utf-8")
    segs = segment_claim(text)
    # Both claims are about a "로봇 매니퓰레이터".
    assert "매니퓰레이터" in segs[0].preamble
    assert "매니퓰레이터" in segs[1].preamble


def test_korean_segmenter_finds_five_elements_in_claim_one() -> None:
    text = KO_CLAIM.read_text(encoding="utf-8")
    segs = segment_claim(text)
    # 베이스, 제1 링크, 제2 링크, 그리퍼, 센서 — five semicolon-separated
    # elements.
    assert len(segs[0].elements) == 5, segs[0].elements
    # The elements should still contain the Korean text verbatim.
    assert "베이스" == segs[0].elements[0]
    assert "제1 링크" in segs[0].elements[1]
    assert "그리퍼" in segs[0].elements[3]
    assert "센서" in segs[0].elements[4]


def test_korean_single_claim_without_header_works() -> None:
    """A claim without ``【청구항 1】`` should still segment as claim_1."""
    text = "베이스; 상기 베이스에 결합된 링크;를 포함하는 장치."
    segs = segment_claim(text)
    assert len(segs) == 1
    assert segs[0].claim_id == "claim_1"
    assert segs[0].language == "ko"
    assert len(segs[0].elements) == 2


# ---------------------------------------------------------------------------
# Parser — stub path (no API key)
# ---------------------------------------------------------------------------


def test_korean_parser_stub_emits_classified_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = KO_CLAIM.read_text(encoding="utf-8")
    ir = parse_claim(text)

    # Title is the Korean preamble noun.
    assert "매니퓰레이터" in ir.title

    component_ids = {c.id for c in ir.components}
    # Romanised head nouns drive IDs.
    assert "base" in component_ids
    assert "first_link" in component_ids
    assert "second_link" in component_ids
    assert "gripper" in component_ids
    assert "sensor" in component_ids

    # Embedded "회전 가능하게 결합된" hints emit revolute joints.
    revolute = [c for c in ir.components if c.kind == "revolute_joint"]
    assert len(revolute) >= 2, [
        (c.id, c.kind) for c in ir.components
    ]

    # Sensor is functional/sensor.
    sensor = next(c for c in ir.components if c.id == "sensor")
    assert sensor.category == "functional"
    assert sensor.kind == "sensor"

    # Gripper is functional/end_effector.
    gripper = next(c for c in ir.components if c.id == "gripper")
    assert gripper.category == "functional"
    assert gripper.kind == "end_effector"

    # Dependent components carry depends_on pointing at claim_1.
    dependent = [c for c in ir.components if c.is_dependent]
    assert dependent, "claim_2 should contribute at least one dependent component"
    for c in dependent:
        assert c.dependent_on == "claim_1"


def test_korean_parser_stub_provenance_spans_into_claim_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = KO_CLAIM.read_text(encoding="utf-8")
    ir = parse_claim(text)
    claim_texts = {c.id: c.text for c in ir.claims}
    for comp in ir.components:
        ct = claim_texts[comp.source_span.claim_id]
        assert 0 <= comp.source_span.char_start < comp.source_span.char_end <= len(ct)
        # The slice should be a non-empty substring inside the claim text.
        assert ct[comp.source_span.char_start : comp.source_span.char_end].strip()


def test_korean_parser_stub_handles_claim_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = "베이스; 상기 베이스에 회전 가능하게 결합된 링크;를 포함하는 장치."
    ir = parse_claim(text)
    component_ids = {c.id for c in ir.components}
    assert "base" in component_ids
    assert "link" in component_ids
    revolute = [c for c in ir.components if c.kind == "revolute_joint"]
    assert revolute, "expected a revolute joint inferred from the embedded hint"


# ---------------------------------------------------------------------------
# IR generation — expected_ir.json validates and uses Korean labels
# ---------------------------------------------------------------------------


def test_korean_expected_ir_validates() -> None:
    ir = ClaimIR.model_validate_json(KO_EXPECTED_IR.read_text(encoding="utf-8"))
    assert ir.title  # Korean noun phrase
    assert any(c.id == "base" for c in ir.components)
    assert any(c.kind == "revolute_joint" or c.kind == "rod" for c in ir.components)


def test_korean_expected_ir_spans_index_into_claim_text() -> None:
    ir = ClaimIR.model_validate_json(KO_EXPECTED_IR.read_text(encoding="utf-8"))
    claim_texts = {c.id: c.text for c in ir.claims}
    for comp in ir.components:
        ct = claim_texts[comp.source_span.claim_id]
        slice_ = ct[comp.source_span.char_start : comp.source_span.char_end]
        assert slice_.strip(), (comp.id, comp.source_span)


# ---------------------------------------------------------------------------
# End-to-end pipeline (dry-run path uses expected_ir.json)
# ---------------------------------------------------------------------------


def test_korean_pipeline_dry_run(tmp_path: Path) -> None:
    from claim2cad.pipeline import run_pipeline

    artifacts = run_pipeline(
        claim_path=KO_CLAIM,
        out_dir=tmp_path,
        dry_run=True,
        write_generator=False,
    )
    assert artifacts["step"].exists() and artifacts["step"].stat().st_size > 1000
    assert artifacts["glb"].exists() and artifacts["glb"].stat().st_size > 1000
    assert artifacts["claim_ir"].exists()
    # The generated IR matches the expected one (same components count).
    ir = ClaimIR.model_validate_json(artifacts["claim_ir"].read_text("utf-8"))
    expected = ClaimIR.model_validate_json(KO_EXPECTED_IR.read_text("utf-8"))
    assert len(ir.components) == len(expected.components)
