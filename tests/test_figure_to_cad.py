"""Tests for claim2cad.figure_to_cad — the V11-3 figure-driven generator.

Live VLM behaviour is exercised manually via the CLI. These tests cover
the deterministic glue: spec parsing, IR-completeness fallback, library
instantiation, and primitive fallback when no library entry matches.
"""
from __future__ import annotations

from pathlib import Path

import build123d as bd
import pytest

from claim2cad.figure_to_cad import (
    ComponentSpec,
    FigureSpec,
    _instantiate_component,
    _parse_figure_spec,
    generate_assembly,
)
from claim2cad.ir_schema import (
    ClaimIR,
    Claim,
    Component,
    DimensionUnspecified,
    SourceSpan,
)


def _ir_with(components: list[Component]) -> ClaimIR:
    return ClaimIR(
        title="Test patent",
        claims=[
            Claim(
                id="claim_1",
                text="Test claim.",
                is_independent=True,
                depends_on=None,
            )
        ],
        components=components,
        relations=[],
    )


def _component(id: str, kind: str = "plate", category: str = "structural") -> Component:
    return Component(
        id=id,
        label=id.replace("_", " "),
        category=category,
        kind=kind,
        parent_id=None,
        dimension=DimensionUnspecified(),
        constraints=[],
        source_span=SourceSpan(claim_id="claim_1", char_start=0, char_end=4),
    )


# ---------------------------------------------------------------------------
# _parse_figure_spec
# ---------------------------------------------------------------------------


def test_parse_figure_spec_drops_unknown_ids() -> None:
    ir = _ir_with([_component("a"), _component("b")])
    raw = {
        "components": [
            {"component_id": "a", "library_part": "plate"},
            {"component_id": "ghost", "library_part": "rod"},
        ]
    }
    spec = _parse_figure_spec(raw, ir, figure_id="figure_1")
    ids = {c.component_id for c in spec.components}
    # ghost dropped, 'b' added as missing-from-spec stub.
    assert ids == {"a", "b"}


def test_parse_figure_spec_fills_missing_with_null_part() -> None:
    ir = _ir_with([_component("a"), _component("b")])
    raw = {"components": [{"component_id": "a", "library_part": "plate"}]}
    spec = _parse_figure_spec(raw, ir, figure_id="figure_1")
    by_id = {c.component_id: c for c in spec.components}
    assert by_id["a"].library_part == "plate"
    assert by_id["b"].library_part is None
    assert "missing" in by_id["b"].notes.lower()


def test_parse_figure_spec_normalises_position_and_rotation() -> None:
    ir = _ir_with([_component("a")])
    raw = {
        "components": [
            {"component_id": "a", "library_part": "plate", "position_mm": [10, 20]}
        ]
    }
    spec = _parse_figure_spec(raw, ir, figure_id="figure_1")
    assert spec.components[0].position_mm == (10.0, 20.0, 0.0)
    assert spec.components[0].rotation_deg == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# _instantiate_component
# ---------------------------------------------------------------------------


def _ir_comp(id: str, kind: str, category: str = "structural") -> Component:
    return Component(
        id=id,
        label=id.replace("_", " "),
        category=category,
        kind=kind,
        parent_id=None,
        dimension=DimensionUnspecified(),
        constraints=[],
        source_span=SourceSpan(claim_id="claim_1", char_start=0, char_end=4),
    )


def test_instantiate_uses_library_when_part_known() -> None:
    spec = ComponentSpec(
        component_id="x",
        library_part="rod",
        params={"length": 40.0, "diameter": 5.0},
    )
    solid, tag = _instantiate_component(spec, _ir_comp("x", "rod"))
    bb = solid.bounding_box()
    assert bb.size.Z == pytest.approx(40.0, abs=0.01)
    assert tag == "library:rod"


def test_instantiate_falls_back_to_primitive_for_unknown_part() -> None:
    spec = ComponentSpec(component_id="x", library_part="not_a_real_thing")
    solid, tag = _instantiate_component(spec, _ir_comp("x", "block"))
    bb = solid.bounding_box()
    # Default fallback for unknown structural is a 20x20x20 box.
    assert bb.size.X == pytest.approx(20.0, abs=0.01)
    assert tag == "primitive"


def test_instantiate_falls_back_when_no_library_part() -> None:
    spec = ComponentSpec(component_id="x", library_part=None)
    solid, tag = _instantiate_component(
        spec, _ir_comp("x", "pin", category="connection")
    )
    # Pin fallback is a small cylinder (r=3, h=14).
    bb = solid.bounding_box()
    assert bb.size.Z == pytest.approx(14.0, abs=0.01)
    assert tag == "primitive"


# ---------------------------------------------------------------------------
# generate_assembly
# ---------------------------------------------------------------------------


def test_generate_assembly_skips_components_marked_covered(tmp_path: Path) -> None:
    ir = _ir_with(
        [
            _component("hinge"),
            _component("leaf_a"),
            _component("pin", kind="pin", category="connection"),
        ]
    )
    spec = FigureSpec(
        patent_id="t",
        figure_id="figure_1",
        components=[
            ComponentSpec(component_id="hinge", library_part="leaf_hinge"),
            ComponentSpec(
                component_id="leaf_a",
                library_part=None,
                notes="covered by leaf_hinge",
            ),
            ComponentSpec(
                component_id="pin",
                library_part=None,
                notes="covered by leaf_hinge",
            ),
        ],
    )
    compound, ordered, _ = generate_assembly(spec, ir)
    assert ordered == ["hinge"]  # leaf_a + pin skipped


def test_generate_assembly_writes_component_steps(tmp_path: Path) -> None:
    ir = _ir_with([_component("a"), _component("b", kind="rod")])
    spec = FigureSpec(
        patent_id="t",
        figure_id="figure_1",
        components=[
            ComponentSpec(
                component_id="a",
                library_part="plate",
                position_mm=(0.0, 0.0, 0.0),
            ),
            ComponentSpec(
                component_id="b",
                library_part="rod",
                position_mm=(50.0, 0.0, 0.0),
            ),
        ],
    )
    components_dir = tmp_path / "components"
    compound, ordered, _ = generate_assembly(spec, ir, components_dir=components_dir)
    assert ordered == ["a", "b"]
    assert (components_dir / "a.step").exists()
    assert (components_dir / "b.step").exists()
    # The compound should fit both placed parts.
    bb = compound.bounding_box()
    assert bb.size.X >= 50.0


def test_generate_assembly_applies_rotation() -> None:
    ir = _ir_with([_component("a", kind="rod")])
    # A 50mm rod rotated 90° about Y is still 50mm long, but along X now.
    spec = FigureSpec(
        patent_id="t",
        figure_id="figure_1",
        components=[
            ComponentSpec(
                component_id="a",
                library_part="rod",
                params={"length": 50.0, "diameter": 6.0},
                rotation_deg=(0.0, 90.0, 0.0),
            )
        ],
    )
    compound, _, _ = generate_assembly(spec, ir)
    bb = compound.bounding_box()
    assert bb.size.X == pytest.approx(50.0, abs=0.5)


def test_figure_spec_dict_round_trip() -> None:
    spec = FigureSpec(
        patent_id="t",
        figure_id="figure_1",
        components=[
            ComponentSpec(
                component_id="a",
                library_part="plate",
                params={"length": 30.0},
                position_mm=(1.0, 2.0, 3.0),
                rotation_deg=(10.0, 0.0, 0.0),
                features=["holes"],
                notes="ok",
            )
        ],
        raw={"vlm_call_id": "abc"},
    )
    d = spec.to_dict()
    rebuilt = FigureSpec.from_dict(d)
    assert rebuilt.patent_id == "t"
    assert rebuilt.components[0].component_id == "a"
    assert rebuilt.components[0].position_mm == (1.0, 2.0, 3.0)
    assert rebuilt.raw == {"vlm_call_id": "abc"}
