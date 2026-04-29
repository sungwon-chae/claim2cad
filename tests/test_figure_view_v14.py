"""V14-B — figure view classifier tests.

Acceptance gates:
* US3705522A_planetary_gear_with_idler is a multi_view_sheet
  (sectional + plan).
* US4807331A_spring_loaded_hinge is oblique-class (oblique /
  multi_view_sheet, both acceptable).
* US5180955A_positioning_apparatus_for_arm is oblique
  (NOT a top/front).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claim2cad.figure_view_v14 import classify_example, classify_figure

REAL = Path("examples/real_patents")


def _have(ex: str) -> bool:
    return (REAL / ex / "figures" / "figure_1.png").exists()


@pytest.mark.skipif(not _have("US3705522A_planetary_gear_with_idler"),
                     reason="corpus not present")
def test_planetary_is_multi_view():
    rep = classify_example(REAL / "US3705522A_planetary_gear_with_idler")
    assert rep.view_type == "multi_view_sheet", rep.evidence
    sub = [r.view_type for r in rep.view_regions]
    assert any(v in ("sectional", "plan", "oblique") for v in sub), sub


@pytest.mark.skipif(not _have("US4807331A_spring_loaded_hinge"),
                     reason="corpus not present")
def test_flagship_hinge_is_oblique_class():
    rep = classify_example(REAL / "US4807331A_spring_loaded_hinge")
    assert rep.view_type in ("oblique", "multi_view_sheet"), rep.evidence


@pytest.mark.skipif(not _have("US5180955A_positioning_apparatus_for_arm"),
                     reason="corpus not present")
def test_positioning_is_oblique_class():
    rep = classify_example(
        REAL / "US5180955A_positioning_apparatus_for_arm")
    assert rep.view_type in ("oblique", "multi_view_sheet"), rep.evidence
    assert rep.required_camera in ("patent_oblique", "iso"), rep


@pytest.mark.skipif(not _have("US4470181A_self_closing_hinge"),
                     reason="corpus not present")
def test_self_closing_hinge_view_is_chosen():
    rep = classify_example(REAL / "US4470181A_self_closing_hinge")
    assert rep.view_type in ("oblique", "multi_view_sheet",
                              "front"), rep.evidence


def test_classifier_returns_known_camera():
    """Smoke: any view_type returned must map to a known camera."""
    fake_path = Path("examples/real_patents/US4807331A_spring_loaded_hinge"
                       "/figures/figure_1.png")
    if not fake_path.exists():
        pytest.skip("figure missing")
    from claim2cad.figure_view_v14 import VIEW_CAMERA
    rep = classify_figure(fake_path, example_id="x")
    assert rep.required_camera in set(VIEW_CAMERA.values())
