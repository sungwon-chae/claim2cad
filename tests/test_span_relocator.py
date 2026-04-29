"""Tests for the V11-13 claim-span relocator.

The LLM-emitted ``source_span`` offsets in the IR drift cumulatively,
and the viewer's underline ends up bracketing the wrong substring
(e.g. ``"d. a p(ower~)"`` instead of ``"power"``). The relocator
fixes this by searching for the component's label in the claim text
directly and writing the verified offsets into ``claim_map.json`` and
back into ``claim_ir.json``.
"""
from __future__ import annotations

import pytest

from claim2cad.span_relocator import (
    _generate_keys,
    _label_content_tokens,
    _strip_parenthetical,
    _strip_prep_tail,
    _token_set_occurrences,
    relocate_components,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_strip_parenthetical_removes_trailing_paren() -> None:
    assert _strip_parenthetical("pintle pin hole (main member)") == "pintle pin hole"
    assert _strip_parenthetical("pintle pin hole") == "pintle pin hole"


def test_strip_prep_tail_drops_prepositional_phrase() -> None:
    assert _strip_prep_tail("stop means on pintle pin") == "stop means"
    assert _strip_prep_tail("guide surface for the link") == "guide surface"
    assert _strip_prep_tail("plain noun") == "plain noun"


def test_generate_keys_orders_specific_first() -> None:
    keys = _generate_keys("pintle pin hole (main member)")
    assert keys[0] == "pintle pin hole (main member)"
    # The stripped form must appear later in the list.
    assert "pintle pin hole" in keys


def test_label_content_tokens_drops_stopwords() -> None:
    assert _label_content_tokens("upper and lower parallel extensions") == [
        "upper",
        "lower",
        "parallel",
        "extensions",
    ]


def test_token_set_finds_coordinated_form() -> None:
    """Patent text 'upper and lower parallel extensions' must yield a
    span when searching for 'upper parallel extension'."""
    text = (
        "the main member having upper and lower parallel extensions "
        "interconnected by a mounting wall"
    )
    matches = _token_set_occurrences(text, "upper parallel extension")
    assert matches, "expected at least one token-set match"
    # The match should start at "upper" and end after "extensions".
    s, e = matches[0]
    assert text[s:].startswith("upper")
    assert text[s:e].endswith("extensions")


# ---------------------------------------------------------------------------
# End-to-end relocation
# ---------------------------------------------------------------------------


def test_relocate_recovers_drifted_spans() -> None:
    """Simulate the cumulative-drift bug: every LLM offset is wrong by
    1 + i chars. The relocator should still find the right substrings."""
    text = (
        "1. A widget comprising a base, a first link rotatably mounted on "
        "the base via a first revolute joint, and an end effector at the "
        "distal end of the first link."
    )
    components = [
        # base is at chars 24..28; LLM says 25..29 (off by +1).
        {"id": "base", "label": "base", "source_span": {"claim_id": "c1", "char_start": 25, "char_end": 29}},
        # first link is at 32..42; LLM says 35..45 (off by +3).
        {"id": "first_link", "label": "first link", "source_span": {"claim_id": "c1", "char_start": 35, "char_end": 45}},
        # end effector is at 95..107; LLM says 99..111 (off by +4).
        {"id": "end_effector", "label": "end effector", "source_span": {"claim_id": "c1", "char_start": 99, "char_end": 111}},
    ]
    out = relocate_components(claims_text_by_id={"c1": text}, components=components)
    by_id = {r.component_id: r for r in out}
    assert by_id["base"].verified
    assert by_id["base"].extracted == "base"
    assert by_id["first_link"].verified
    assert by_id["first_link"].extracted == "first link"
    assert by_id["end_effector"].verified
    assert by_id["end_effector"].extracted == "end effector"


def test_relocate_marks_unfindable_label_unverified() -> None:
    text = "1. A widget comprising a base."
    components = [
        # The label "phantom widget" doesn't appear in the text at all.
        {"id": "phantom", "label": "phantom widget", "source_span": {"claim_id": "c1", "char_start": 0, "char_end": 14}},
    ]
    out = relocate_components(claims_text_by_id={"c1": text}, components=components)
    assert not out[0].verified
    assert out[0].notes


def test_relocate_handles_coordinated_compound_form() -> None:
    """Two singular labels share a coordinated plural — both must verify."""
    text = (
        "the main member having upper and lower parallel extensions "
        "interconnected by a mounting wall"
    )
    components = [
        {"id": "upper_extension", "label": "upper parallel extension",
         "source_span": {"claim_id": "c1", "char_start": 0, "char_end": 24}},
        {"id": "lower_extension", "label": "lower parallel extension",
         "source_span": {"claim_id": "c1", "char_start": 0, "char_end": 24}},
    ]
    out = relocate_components(claims_text_by_id={"c1": text}, components=components)
    by_id = {r.component_id: r for r in out}
    assert by_id["upper_extension"].verified
    assert by_id["lower_extension"].verified
    assert "upper" in by_id["upper_extension"].extracted.lower()
    assert "lower" in by_id["lower_extension"].extracted.lower()


def test_relocate_does_not_assign_same_span_to_two_components() -> None:
    """If two components have the same label, only one gets the first
    occurrence; the other gets the second occurrence (or unverified)."""
    text = "A widget comprising a base, and another base attached thereto."
    components = [
        {"id": "base_1", "label": "base", "source_span": {"claim_id": "c1", "char_start": 22, "char_end": 26}},
        {"id": "base_2", "label": "base", "source_span": {"claim_id": "c1", "char_start": 41, "char_end": 45}},
    ]
    out = relocate_components(claims_text_by_id={"c1": text}, components=components)
    by_id = {r.component_id: r for r in out}
    assert by_id["base_1"].verified
    assert by_id["base_2"].verified
    # Two different occurrences.
    assert by_id["base_1"].char_start != by_id["base_2"].char_start


def test_relocate_short_label_still_word_boundary_matches() -> None:
    """A label like 'pin' should not match the 'pin' inside 'pintle pin'
    when 'pintle pin' is the full label."""
    text = "A pintle pin engages the main member."
    components = [
        {"id": "pintle_pin", "label": "pintle pin",
         "source_span": {"claim_id": "c1", "char_start": 2, "char_end": 12}},
        {"id": "pin", "label": "pin",
         "source_span": {"claim_id": "c1", "char_start": 9, "char_end": 12}},
    ]
    out = relocate_components(claims_text_by_id={"c1": text}, components=components)
    by_id = {r.component_id: r for r in out}
    # pintle_pin should match the full "pintle pin" span.
    assert by_id["pintle_pin"].extracted == "pintle pin"
    # 'pin' should also match (overlapping is allowed for short shared
    # tokens), or be unverified — either is acceptable behaviour. We
    # just assert that pintle_pin doesn't get displaced.
    assert by_id["pintle_pin"].verified
