"""Tests for V11-29 / V11-30 / V11-32 figure hotspot pipeline."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from claim2cad.figure_hotspots import (
    COORD_SPACE_IMAGE_PIXEL,
    FigureHotspot,
    FigureHotspotSet,
    _bbox_around_centre,
    _norm_to_px,
    build_hotspots_for_example,
    load_hotspots,
    save_hotspots,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_norm_to_px_centre() -> None:
    px = _norm_to_px((0.5, 0.5), 1000, 800)
    assert px == (500.0, 400.0)


def test_norm_to_px_clamps_to_image_bounds() -> None:
    # u and v outside [0, 1] should clamp.
    px = _norm_to_px((-0.1, 1.5), 1000, 800)
    assert px[0] >= 0.0
    assert px[1] <= 800.0


def test_bbox_around_centre_stays_in_bounds() -> None:
    bb = _bbox_around_centre((10.0, 5.0), 1000, 800, radius_frac=0.04)
    # x0/y0 cannot go negative.
    assert bb[0] >= 0.0
    assert bb[1] >= 0.0
    # x1/y1 cannot exceed image bounds.
    assert bb[2] <= 999.0
    assert bb[3] <= 799.0


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


def test_hotspot_schema_round_trip(tmp_path: Path) -> None:
    hs = FigureHotspotSet(
        figure_id="figure_1",
        figure_path="figures/figure_1.png",
        image_width_px=2000,
        image_height_px=3000,
        hotspots=[
            FigureHotspot(
                hotspot_id="pintle_pin_22",
                figure_id="figure_1",
                component_id="pintle_pin",
                callout_number="22",
                label="pintle pin",
                coord_space=COORD_SPACE_IMAGE_PIXEL,
                image_width_px=2000,
                image_height_px=3000,
                center_px=(700.0, 660.0),
                bbox_px=(620.0, 580.0, 780.0, 740.0),
                confidence=0.85,
                source="figure_projection",
            ),
        ],
    )
    p = save_hotspots(hs, tmp_path / "fh.json")
    loaded = load_hotspots(p)
    assert loaded.figure_id == "figure_1"
    assert len(loaded.hotspots) == 1
    h = loaded.hotspots[0]
    assert h.component_id == "pintle_pin"
    assert h.coord_space == COORD_SPACE_IMAGE_PIXEL
    assert h.center_px == (700.0, 660.0)
    assert h.source == "figure_projection"


# ---------------------------------------------------------------------------
# Fixture-based regression — US4807331A
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
US4807331A = REPO_ROOT / "examples/real_patents/US4807331A_spring_loaded_hinge"


@pytest.mark.skipif(
    not (US4807331A / "figure_projection.json").exists(),
    reason="figure_projection.json absent — V11-23 must run first",
)
def test_us4807331a_hotspots_built() -> None:
    hs = build_hotspots_for_example(example_dir=US4807331A)
    assert hs is not None
    assert len(hs.hotspots) >= 20


@pytest.mark.skipif(
    not (US4807331A / "figure_projection.json").exists(),
    reason="figure_projection.json absent",
)
def test_us4807331a_hotspots_in_image_bounds() -> None:
    hs = build_hotspots_for_example(example_dir=US4807331A)
    assert hs is not None
    for h in hs.hotspots:
        cx, cy = h.center_px
        assert 0 <= cx <= h.image_width_px
        assert 0 <= cy <= h.image_height_px
        x0, y0, x1, y1 = h.bbox_px
        assert x0 >= 0 and y0 >= 0
        assert x1 <= h.image_width_px and y1 <= h.image_height_px
        assert x1 > x0 and y1 > y0


@pytest.mark.skipif(
    not (US4807331A / "figure_projection.json").exists(),
    reason="figure_projection.json absent",
)
def test_us4807331a_hotspots_have_valid_component_ids() -> None:
    """Every hotspot's component_id must exist in claim_map.json."""
    hs = build_hotspots_for_example(example_dir=US4807331A)
    assert hs is not None
    cm = json.loads((US4807331A / "claim_map.json").read_text("utf-8"))
    valid_ids = {r["component_id"] for r in cm["components"]}
    for h in hs.hotspots:
        if h.component_id is None:
            continue
        assert h.component_id in valid_ids, f"hotspot for unknown id {h.component_id}"


@pytest.mark.skipif(
    not (US4807331A / "figure_projection.json").exists(),
    reason="figure_projection.json absent",
)
def test_us4807331a_hotspots_not_all_clustered() -> None:
    """The hotspots should NOT all collapse to the same image region.
    Patent figure 1 spreads components across u ∈ [0.35, 0.80] and
    v ∈ [0.22, 0.62]; the hotspot centres should reflect that."""
    hs = build_hotspots_for_example(example_dir=US4807331A)
    assert hs is not None
    if not hs.hotspots:
        pytest.skip("no hotspots")
    W = hs.image_width_px
    H = hs.image_height_px
    xs_norm = [h.center_px[0] / max(W, 1) for h in hs.hotspots]
    ys_norm = [h.center_px[1] / max(H, 1) for h in hs.hotspots]
    assert max(xs_norm) - min(xs_norm) > 0.20, "hotspots collapsed in U"
    assert max(ys_norm) - min(ys_norm) > 0.20, "hotspots collapsed in V"


@pytest.mark.skipif(
    not (US4807331A / "figure_projection.json").exists(),
    reason="figure_projection.json absent",
)
def test_us4807331a_hotspots_image_bounds_match_actual_figure() -> None:
    hs = build_hotspots_for_example(example_dir=US4807331A)
    assert hs is not None
    img = Image.open(US4807331A / "figures" / "figure_1.png")
    assert hs.image_width_px == img.size[0]
    assert hs.image_height_px == img.size[1]
