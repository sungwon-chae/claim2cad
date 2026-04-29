"""Tests for V11-23b figure projection coordinate model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claim2cad.figure_projection import (
    FigureAnchor,
    FigureProjection,
    FigureProjectionLayout,
    build_projection,
    figure_anchors_for_components,
    group_anchors_from_components,
    load_layout,
    projection_for_view,
    save_layout,
)


# ---------------------------------------------------------------------------
# projection_for_view
# ---------------------------------------------------------------------------


def test_projection_for_view_top_uses_xy_plane() -> None:
    plane, depth = projection_for_view("top")
    assert plane == ("X", "Y")
    assert depth == "Z"


def test_projection_for_view_front_uses_xz_plane() -> None:
    plane, depth = projection_for_view("front")
    assert plane == ("X", "Z")
    assert depth == "Y"


def test_projection_for_view_iso_treated_as_front_like() -> None:
    plane, depth = projection_for_view("iso")
    assert plane == ("X", "Z")
    assert depth == "Y"


def test_projection_for_view_unknown_falls_back() -> None:
    plane, depth = projection_for_view("zzz")
    assert plane == ("X", "Z")  # iso default


# ---------------------------------------------------------------------------
# FigureProjection — uv ↔ world
# ---------------------------------------------------------------------------


def test_uv_to_world_centre_maps_to_origin() -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=2000,
        figure_height_px=2000,
        scale_uv_to_mm=200.0,
    )
    x, y, z = p.uv_to_world((0.5, 0.5))
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(0.0)
    assert z == pytest.approx(0.0)


def test_uv_to_world_image_corners_span_scale() -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=1000,
        figure_height_px=1000,
        scale_uv_to_mm=200.0,
    )
    # Top-left corner: u=0, v=0  ⇒  x = -100, z = +100 (v flipped)
    x, _, z = p.uv_to_world((0.0, 0.0))
    assert x == pytest.approx(-100.0)
    assert z == pytest.approx(+100.0)
    # Bottom-right corner: u=1, v=1  ⇒  x = +100, z = -100
    x, _, z = p.uv_to_world((1.0, 1.0))
    assert x == pytest.approx(+100.0)
    assert z == pytest.approx(-100.0)


def test_uv_to_world_top_view() -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="top",
        figure_width_px=1000,
        figure_height_px=1000,
        scale_uv_to_mm=200.0,
    )
    # Top view: u→X, v→-Y; depth Z stays at depth_value
    x, y, z = p.uv_to_world((0.5, 0.0))
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(+100.0)  # v=0 → top of figure → +Y
    assert z == pytest.approx(0.0)  # default depth


def test_world_to_uv_round_trip() -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=1500,
        figure_height_px=1500,
        scale_uv_to_mm=300.0,
    )
    for uv in [(0.1, 0.1), (0.5, 0.5), (0.9, 0.7)]:
        xyz = p.uv_to_world(uv)
        uv2 = p.world_to_uv(xyz)
        assert uv2[0] == pytest.approx(uv[0], abs=1e-6)
        assert uv2[1] == pytest.approx(uv[1], abs=1e-6)


def test_aspect_handles_landscape_and_portrait() -> None:
    landscape = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=2000,
        figure_height_px=1000,
    )
    assert landscape.width_mm() == 200.0
    assert landscape.height_mm() == 100.0
    portrait = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=1000,
        figure_height_px=2000,
    )
    assert portrait.width_mm() == 100.0
    assert portrait.height_mm() == 200.0


# ---------------------------------------------------------------------------
# figure_anchors_for_components
# ---------------------------------------------------------------------------


def test_figure_anchors_emits_one_per_bound_component() -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="front",
        figure_width_px=1000,
        figure_height_px=1000,
        scale_uv_to_mm=200.0,
    )
    fmap = {
        "vlm_labels": [
            {"number": "1", "approximate_position": [0.2, 0.3]},
            {"number": "2", "approximate_position": [0.8, 0.7]},
        ],
        "component_to_number": {
            "comp_a": "1",
            "comp_b": "2",
        },
    }
    anchors = figure_anchors_for_components(figure_map=fmap, projection=p)
    assert len(anchors) == 2
    # Order is dict-insertion; test by id
    by_id = {a.id: a for a in anchors}
    assert by_id["comp_a"].figure_uv == (0.2, 0.3)
    assert by_id["comp_b"].figure_uv == (0.8, 0.7)
    # CAD coords reasonable (front view: u→X, v→-Z)
    a_x, _, a_z = by_id["comp_a"].cad_anchor_mm
    assert a_x < 0  # u=0.2 left of centre → -X
    assert a_z > 0  # v=0.3 above centre (image) → +Z


def test_figure_anchors_skips_components_without_position() -> None:
    p = build_projection(
        figure_id="f", view_kind="front",
        figure_width_px=1000, figure_height_px=1000,
    )
    fmap = {
        "vlm_labels": [],
        "component_to_number": {"orphan": "99"},
    }
    anchors = figure_anchors_for_components(figure_map=fmap, projection=p)
    assert anchors == []


# ---------------------------------------------------------------------------
# group_anchors_from_components
# ---------------------------------------------------------------------------


def test_group_anchor_is_median_of_members() -> None:
    p = build_projection(
        figure_id="f", view_kind="front",
        figure_width_px=1000, figure_height_px=1000, scale_uv_to_mm=200.0,
    )
    component_anchors = [
        FigureAnchor(id="a", figure_uv=(0.1, 0.4), cad_anchor_mm=p.uv_to_world((0.1, 0.4))),
        FigureAnchor(id="b", figure_uv=(0.3, 0.5), cad_anchor_mm=p.uv_to_world((0.3, 0.5))),
        FigureAnchor(id="c", figure_uv=(0.5, 0.6), cad_anchor_mm=p.uv_to_world((0.5, 0.6))),
    ]
    group_anchors = group_anchors_from_components(
        component_anchors=component_anchors,
        component_to_group={"a": "G", "b": "G", "c": "G"},
        projection=p,
    )
    assert len(group_anchors) == 1
    g = group_anchors[0]
    assert g.figure_uv == (pytest.approx(0.3), pytest.approx(0.5))


def test_group_anchor_default_for_groups_without_members() -> None:
    p = build_projection(
        figure_id="f", view_kind="front",
        figure_width_px=1000, figure_height_px=1000, scale_uv_to_mm=200.0,
    )
    group_anchors = group_anchors_from_components(
        component_anchors=[],
        component_to_group={},
        projection=p,
        extra_groups=("fasteners",),
    )
    assert len(group_anchors) == 1
    assert group_anchors[0].id == "fasteners"
    assert group_anchors[0].figure_uv == (0.5, 0.5)


# ---------------------------------------------------------------------------
# JSON round trip
# ---------------------------------------------------------------------------


def test_layout_save_load_round_trip(tmp_path: Path) -> None:
    p = build_projection(
        figure_id="figure_1",
        view_kind="iso",
        figure_width_px=2320,
        figure_height_px=3408,
        scale_uv_to_mm=200.0,
    )
    layout = FigureProjectionLayout(
        projection=p,
        component_anchors=[
            FigureAnchor(id="a", figure_uv=(0.1, 0.2), cad_anchor_mm=(1.0, 0.0, 30.0)),
        ],
        group_anchors=[
            FigureAnchor(id="upper_hinge", figure_uv=(0.5, 0.4), cad_anchor_mm=(0.0, 0.0, 50.0)),
        ],
    )
    p_path = save_layout(layout, tmp_path / "fp.json")
    re = load_layout(p_path)
    assert re.projection.figure_id == "figure_1"
    assert re.projection.view_type == "iso"
    assert re.projection.projection_plane == ("X", "Z")
    assert re.component_anchors[0].id == "a"
    assert re.group_anchors[0].id == "upper_hinge"
