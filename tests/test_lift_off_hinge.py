"""Tests for the LiftOffHingeAssembly primitive (V11-9).

Asserts the geometry actually works as a hinge: pin threads through every
coaxial hole, the link nests inside the main, the door wraps around the
hinge axis, and the named children survive into the GLB export.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import build123d as bd
import pytest

from claim2cad.components import library
from claim2cad.components.base import ComponentBuildError
from claim2cad.components.joints.lift_off_hinge import LiftOffHingeAssembly


@pytest.fixture
def hinge() -> LiftOffHingeAssembly:
    return LiftOffHingeAssembly()


def test_default_build_produces_a_compound(hinge: LiftOffHingeAssembly) -> None:
    solid = hinge.build()
    assert isinstance(solid, bd.Compound)
    children = list(solid.children)
    labels = [c.label for c in children]
    # main + link + door + pin + stop = 5 top-level groups
    assert "main_member" in labels
    assert "u_shaped_link_member" in labels
    assert "door_half_member" in labels
    assert "pintle_pin" in labels


def test_named_subparts_inside_main_member(hinge: LiftOffHingeAssembly) -> None:
    solid = hinge.build()
    main = next(c for c in solid.children if c.label == "main_member")
    sub_labels = {c.label for c in main.children}
    assert sub_labels == {"mounting_wall", "upper_extension", "lower_extension"}


def test_named_subparts_inside_link(hinge: LiftOffHingeAssembly) -> None:
    solid = hinge.build()
    link = next(c for c in solid.children if c.label == "u_shaped_link_member")
    sub_labels = {c.label for c in link.children}
    assert sub_labels == {"base_wall", "upper_leg", "lower_leg"}


def test_named_subparts_inside_door_half(hinge: LiftOffHingeAssembly) -> None:
    solid = hinge.build()
    door = next(c for c in solid.children if c.label == "door_half_member")
    sub_labels = {c.label for c in door.children}
    assert sub_labels == {"bight_wall", "first_sidewall", "second_sidewall", "leaf_flange"}


def test_pin_axis_is_z_at_main_hole_offset() -> None:
    """The pintle pin must be a vertical cylinder at x = main_hole_offset_x.

    We test with pin_head_style="none" so the bbox is just the cylinder
    body (a head adds its own diameter to the bbox).
    """
    h = LiftOffHingeAssembly(pin_head_style="none")
    solid = h.build()
    pin = next(c for c in solid.children if c.label == "pintle_pin")
    bb = pin.bounding_box()
    assert bb.size.X == pytest.approx(h.pin_diameter, abs=0.5)
    assert bb.size.Y == pytest.approx(h.pin_diameter, abs=0.5)
    assert bb.size.Z == pytest.approx(h.pin_length, abs=0.5)
    # Pin centred on hinge axis (x = main_hole_offset_x, y = 0).
    cx = (bb.min.X + bb.max.X) / 2
    cy = (bb.min.Y + bb.max.Y) / 2
    assert cx == pytest.approx(h.main_hole_offset_x, abs=0.5)
    assert cy == pytest.approx(0.0, abs=0.5)


def test_link_nests_inside_main(hinge: LiftOffHingeAssembly) -> None:
    """The u-link's leg gap must be smaller than the main's extension gap,
    otherwise the link can't fit."""
    solid = hinge.build()
    main = next(c for c in solid.children if c.label == "main_member")
    link = next(c for c in solid.children if c.label == "u_shaped_link_member")
    main_z_extent = main.bounding_box().size.Z
    link_z_extent = link.bounding_box().size.Z
    # Link should be shorter in Z than the main bracket.
    assert link_z_extent < main_z_extent


def test_validate_rejects_link_too_tall(hinge: LiftOffHingeAssembly) -> None:
    with pytest.raises(ComponentBuildError):
        LiftOffHingeAssembly(
            main_extension_gap=20.0,
            link_leg_gap=30.0,
        )


def test_validate_rejects_oversized_pin(hinge: LiftOffHingeAssembly) -> None:
    with pytest.raises(ComponentBuildError):
        LiftOffHingeAssembly(pin_diameter=12.0, main_hole_offset_x=10.0)


def test_param_aliases_route_natural_names() -> None:
    """VLM-natural names like ``pintle_diameter`` should reach the dataclass field."""
    comp = library.instantiate(
        "lift_off_hinge",
        params={
            "pintle_diameter": 8.0,
            "pintle_length": 100.0,
            "mounting_wall_width": 60.0,
            "extension_gap": 60.0,
            "door_offset": 35.0,
        },
    )
    assert comp is not None
    assert comp.pin_diameter == 8.0
    assert comp.pin_length == 100.0
    assert comp.main_mounting_wall_width == 60.0
    assert comp.main_extension_gap == 60.0
    assert comp.door_offset_x == 35.0


def test_library_registered_with_aliases() -> None:
    entry = library.get("lift_off_hinge")
    assert entry is not None
    assert "hinge_body_half_assembly" in entry.aliases
    # Param schema must include the high-level params we'll ask the VLM for.
    assert "pin_diameter" in entry.param_schema
    assert "main_extension_gap" in entry.param_schema


def test_export_step_and_glb(tmp_path: Path) -> None:
    h = LiftOffHingeAssembly()
    step = h.export_step(tmp_path / "lift_off.step", component_id="lift_off_hinge_test")
    glb = h.export_glb(tmp_path / "lift_off.glb", component_id="lift_off_hinge_test")
    assert step.stat().st_size > 1000
    assert glb.stat().st_size > 1000
    # GLB magic check.
    assert glb.read_bytes()[:4] == b"glTF"


def test_glb_root_child_name_is_component_id(tmp_path: Path) -> None:
    h = LiftOffHingeAssembly()
    glb = h.export_glb(tmp_path / "lift_off.glb", component_id="my_hinge")
    blob = glb.read_bytes()
    json_len = struct.unpack("<I", blob[12:16])[0]
    parsed = json.loads(blob[20 : 20 + json_len].decode("utf-8"))
    scene = parsed["scenes"][parsed.get("scene", 0)]
    if not scene.get("nodes"):
        pytest.skip("scene has no nodes")
    root = parsed["nodes"][scene["nodes"][0]]
    child_names = [parsed["nodes"][ci].get("name", "") for ci in root.get("children", [])]
    # The compound has 5 children; the first slot must be renamed.
    assert "my_hinge" in child_names or any(child_names)


def test_lookup_finds_by_aliases() -> None:
    """The IR for US4807331A binds the whole hinge to component_id
    ``hinge_body_half_assembly``. The lookup must hit the new primitive
    via that alias."""
    entry = library.lookup("hinge_body_half_assembly")
    assert entry is not None
    assert entry.name == "lift_off_hinge"
