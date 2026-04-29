"""Tests for the V11-12 outline-first pipeline.

Live VLM behaviour is exercised manually via the CLI. These tests
cover the deterministic glue: polygon-area validation, normalised
crop-coordinate → world-mm mapping, sketch-and-extrude conversion,
and the round-trip OutlineSet ↔ JSON.
"""
from __future__ import annotations

from pathlib import Path

import build123d as bd
import pytest

from claim2cad.figure_crops import FigureCrop
from claim2cad.figure_to_sketch import (
    ComponentOutline,
    OutlineSet,
    _polygon_area,
    _local_to_global_norm,
)
from claim2cad.sketch_to_extrusion import (
    _norm_to_world_xy,
    build_assembly_from_outlines,
    build_extrusion,
)


def test_polygon_area_unit_square_is_one() -> None:
    pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert _polygon_area(pts) == pytest.approx(1.0)


def test_polygon_area_handles_short_polygons() -> None:
    assert _polygon_area([(0, 0), (1, 0)]) == 0.0
    assert _polygon_area([]) == 0.0


def test_local_to_global_norm() -> None:
    crop_box = (0.2, 0.3, 0.4, 0.5)  # x0, y0, x1, y1
    g = _local_to_global_norm((0.5, 0.5), crop_box)
    # midpoint of crop should be at (0.3, 0.4) in figure coords.
    assert g == pytest.approx((0.3, 0.4))


def test_norm_to_world_xy_centres_on_origin() -> None:
    """A polygon with the figure centre included should map (0.5, 0.5) → (0, 0)."""
    pts = [(0.5, 0.5), (0.6, 0.5), (0.5, 0.6)]
    world = _norm_to_world_xy(pts, figure_scale_mm=200.0, aspect=1.0)
    assert world[0] == pytest.approx((0.0, 0.0))
    # x grows right, y grows UP (figure y is flipped).
    assert world[1][0] > 0  # +X
    assert world[2][1] < 0  # -Y in world (because figure y was larger)


def test_norm_to_world_xy_respects_aspect() -> None:
    pts = [(0.0, 0.0), (1.0, 1.0)]
    # Wider than tall (aspect 2): width = 200 mm, height = 100 mm.
    world = _norm_to_world_xy(pts, figure_scale_mm=200.0, aspect=2.0)
    assert world[0][0] == pytest.approx(-100.0)  # -width/2
    assert world[1][0] == pytest.approx(+100.0)  # +width/2
    assert world[0][1] == pytest.approx(+50.0)   # +height/2 (image y=0 → world +y)
    assert world[1][1] == pytest.approx(-50.0)


def test_outline_is_valid_rejects_short_polygons() -> None:
    o = ComponentOutline(component_id="x", figure_number="1", polygon_norm=[(0, 0), (1, 0)])
    assert not o.is_valid()


def test_outline_is_valid_rejects_zero_area() -> None:
    o = ComponentOutline(
        component_id="x",
        figure_number="1",
        polygon_norm=[(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)],
    )
    assert not o.is_valid()


def test_outline_is_valid_accepts_real_polygon() -> None:
    o = ComponentOutline(
        component_id="x",
        figure_number="1",
        polygon_norm=[(0.3, 0.3), (0.5, 0.3), (0.5, 0.5), (0.3, 0.5)],
    )
    assert o.is_valid()


def test_build_extrusion_produces_valid_solid() -> None:
    outline = ComponentOutline(
        component_id="plate",
        figure_number="1",
        polygon_norm=[(0.4, 0.4), (0.6, 0.4), (0.6, 0.5), (0.4, 0.5)],
        extrude_depth_mm=4.0,
    )
    r = build_extrusion(outline, figure_scale_mm=100.0, aspect=1.0)
    assert r.solid is not None
    assert r.bbox_mm is not None
    sx, sy, sz = r.bbox_mm
    # 0.2 of 100 mm = 20 mm in X
    assert sx == pytest.approx(20.0, abs=0.5)
    assert sy == pytest.approx(10.0, abs=0.5)
    assert sz == pytest.approx(4.0, abs=0.5)


def test_build_extrusion_supports_holes() -> None:
    outline = ComponentOutline(
        component_id="plate_with_hole",
        figure_number="1",
        polygon_norm=[(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)],
        holes_norm=[
            [(0.45, 0.45), (0.55, 0.45), (0.55, 0.55), (0.45, 0.55)],
        ],
        extrude_depth_mm=3.0,
    )
    r = build_extrusion(outline, figure_scale_mm=100.0, aspect=1.0)
    assert r.solid is not None
    # Volume should be (40x40x3) - (10x10x3) = 4800 - 300 = 4500 mm^3.
    bb = r.solid.bounding_box()
    assert bb.size.X == pytest.approx(40.0, abs=0.5)
    assert bb.size.Y == pytest.approx(40.0, abs=0.5)
    assert bb.size.Z == pytest.approx(3.0, abs=0.5)


def test_build_extrusion_returns_none_for_degenerate() -> None:
    outline = ComponentOutline(
        component_id="x",
        figure_number="1",
        polygon_norm=[(0.5, 0.5)],  # 1 point
    )
    r = build_extrusion(outline, figure_scale_mm=100.0, aspect=1.0)
    assert r.solid is None


def test_build_assembly_compound_has_named_top_level_children() -> None:
    """This is the critical contract: every component_id is a TOP-LEVEL
    GLB node, so the viewer's traverse → getObjectByName lookup works."""
    outlines = OutlineSet(
        figure_id="figure_1",
        figure_width_px=2000,
        figure_height_px=2000,
        figure_scale_mm=100.0,
        outlines=[
            ComponentOutline(
                component_id=f"part_{i}",
                figure_number=str(i),
                polygon_norm=[
                    (0.1 + 0.1 * i, 0.1),
                    (0.15 + 0.1 * i, 0.1),
                    (0.15 + 0.1 * i, 0.2),
                    (0.1 + 0.1 * i, 0.2),
                ],
                extrude_depth_mm=2.0,
            )
            for i in range(3)
        ],
    )
    compound, ordered, results = build_assembly_from_outlines(outlines)
    assert ordered == ["part_0", "part_1", "part_2"]
    labels = {c.label for c in compound.children}
    assert labels == {"part_0", "part_1", "part_2"}
    for r in results:
        assert r.solid is not None


def test_outline_set_round_trip(tmp_path: Path) -> None:
    o = OutlineSet(
        figure_id="figure_1",
        figure_width_px=1000,
        figure_height_px=1500,
        figure_scale_mm=180.0,
        outlines=[
            ComponentOutline(
                component_id="a",
                figure_number="22",
                polygon_norm=[(0.1, 0.1), (0.2, 0.1), (0.2, 0.2)],
                extrude_depth_mm=5.0,
                z_offset_mm=10.0,
                holes_norm=[[(0.13, 0.13), (0.17, 0.13), (0.17, 0.17)]],
                source="vlm",
                notes="hi",
            )
        ],
    )
    import json
    d = o.to_dict()
    s = json.dumps(d)
    parsed = json.loads(s)
    rebuilt = OutlineSet.from_dict(parsed)
    assert rebuilt.figure_id == "figure_1"
    assert rebuilt.figure_scale_mm == 180.0
    assert rebuilt.outlines[0].component_id == "a"
    assert rebuilt.outlines[0].figure_number == "22"
    assert rebuilt.outlines[0].extrude_depth_mm == 5.0
    assert rebuilt.outlines[0].polygon_norm == [(0.1, 0.1), (0.2, 0.1), (0.2, 0.2)]
    assert rebuilt.outlines[0].holes_norm == [[(0.13, 0.13), (0.17, 0.13), (0.17, 0.17)]]
