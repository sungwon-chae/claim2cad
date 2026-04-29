"""V13-K — regression tests for the refined topology classifier.

These cases capture three semantic mismatches the v1.3 classifier
got wrong before V13-K:

* US5180955A — was rotary_shaft, must be positioning_apparatus.
* US4470181A — was generic door_hinge, must be
  self_closing_hinge_mechanism.
* US3705522A — keeps planetary_gear topology but must route to
  the dedicated planetary_gear scaffold and carry a multi_view
  hint for sectional+plan rendering.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claim2cad.figure_topology_classifier import (
    classify,
    classify_example,
)


REAL_PATENTS = Path("examples/real_patents")


def _claim_map(comp_labels: list[str]) -> dict:
    return {
        "components": [
            {"component_id": f"c{i}", "label": lbl}
            for i, lbl in enumerate(comp_labels)
        ],
    }


def test_positioning_apparatus_beats_rotary_shaft():
    cm = _claim_map([
        "positioning linkage", "parallelogram structure",
        "base structure", "first arm", "center shaft",
        "end-effector", "electromagnetic coil",
    ])
    rep = classify(
        example_id="US5180955A_positioning_apparatus_for_arm",
        claim_map=cm, figure_map=None,
        claim_text="A positioning apparatus comprising a "
                   "parallelogram structure with arms.",
    )
    assert rep.topology == "positioning_apparatus", rep.evidence
    assert rep.recommended_scaffold == "positioning_apparatus"


def test_self_closing_hinge_mechanism_beats_door_hinge():
    cm = _claim_map(["frame", "hinge body", "lever", "spring"])
    rep = classify(
        example_id="US4470181A_self_closing_hinge",
        claim_map=cm, figure_map=None,
        claim_text="A self-closing hinge with a spring loaded closer.",
    )
    assert rep.topology == "self_closing_hinge_mechanism", rep.evidence
    assert rep.recommended_scaffold == "self_closing_hinge_mechanism"


def test_planetary_gear_routes_to_planetary_scaffold_with_multi_view():
    cm = _claim_map([
        "stationary housing", "input shaft", "planet carrier means",
        "first ring gear", "first planet pinion", "output shaft",
    ])
    rep = classify(
        example_id="US3705522A_planetary_gear_with_idler",
        claim_map=cm, figure_map=None,
        claim_text="A planetary gear assembly with an idler.",
    )
    assert rep.topology == "planetary_gear", rep.evidence
    assert rep.recommended_scaffold == "planetary_gear"
    assert rep.multi_view == ["sectional", "plan"]


def test_broad_shaft_keyword_no_longer_wins_over_specific_topologies():
    """Regression: a label that contains 'shaft' must not promote
    an example to rotary_shaft when a more specific topology
    matches earlier."""
    cm = _claim_map([
        "positioning linkage", "center shaft",
    ])
    rep = classify(
        example_id="some_positioner",
        claim_map=cm, figure_map=None,
        claim_text="A positioning apparatus with a central pivot shaft.",
    )
    assert rep.topology == "positioning_apparatus"


def test_broad_rotary_keywords_still_match_when_no_specific_rule_fires():
    cm = _claim_map(["transmission", "rotor", "drive shaft"])
    rep = classify(
        example_id="generic_rotary",
        claim_map=cm, figure_map=None,
        claim_text="A transmission rotor drive shaft assembly.",
    )
    assert rep.topology == "rotary_shaft"
    assert rep.recommended_scaffold == "rotary_shaft"


@pytest.mark.skipif(
    not (REAL_PATENTS / "US5180955A_positioning_apparatus_for_arm" /
         "claim_map.json").exists(),
    reason="real_patents corpus not present",
)
def test_real_corpus_us5180955a_is_positioning_apparatus():
    rep = classify_example(
        REAL_PATENTS / "US5180955A_positioning_apparatus_for_arm")
    assert rep.topology == "positioning_apparatus"
    assert rep.recommended_scaffold == "positioning_apparatus"


@pytest.mark.skipif(
    not (REAL_PATENTS / "US4470181A_self_closing_hinge" /
         "claim_map.json").exists(),
    reason="real_patents corpus not present",
)
def test_real_corpus_us4470181a_is_self_closing_hinge_mechanism():
    rep = classify_example(
        REAL_PATENTS / "US4470181A_self_closing_hinge")
    assert rep.topology == "self_closing_hinge_mechanism"
    assert rep.recommended_scaffold == "self_closing_hinge_mechanism"


@pytest.mark.skipif(
    not (REAL_PATENTS / "US3705522A_planetary_gear_with_idler" /
         "claim_map.json").exists(),
    reason="real_patents corpus not present",
)
def test_real_corpus_us3705522a_is_planetary_gear():
    rep = classify_example(
        REAL_PATENTS / "US3705522A_planetary_gear_with_idler")
    assert rep.topology == "planetary_gear"
    assert rep.recommended_scaffold == "planetary_gear"
    assert "sectional" in rep.multi_view
    assert "plan" in rep.multi_view
