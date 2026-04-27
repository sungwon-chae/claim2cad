"""Phase 3 smoke tests for the end-to-end pipeline.

These run in a tmp_path so they do not overwrite the committed
``examples/golden_robot_arm/`` artifacts. The structural assertions check
that the pipeline:

* writes all four required output files,
* IR validates and round-trips,
* claim_map's component count == IR's component count,
* GLB has at least one named root child whose name matches a component id.

Phase 4+ adds parser-side and CAD-side richness; this file stays as the
"end-to-end smoke" floor.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from claim2cad.ir_schema import ClaimIR
from claim2cad.pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "examples" / "golden_robot_arm"


def _glb_root_child_names(glb_path: Path) -> list[str]:
    glb = glb_path.read_bytes()
    assert glb[:4] == b"glTF", f"{glb_path} is not a binary glTF file"
    json_len = struct.unpack("<I", glb[12:16])[0]
    parsed = json.loads(glb[20 : 20 + json_len].decode("utf-8"))
    scene = parsed["scenes"][parsed.get("scene", 0)]
    root = parsed["nodes"][scene["nodes"][0]]
    return [parsed["nodes"][ci].get("name", "") for ci in root.get("children", [])]


@pytest.fixture(scope="module")
def golden_pipeline_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    out_dir = tmp_path_factory.mktemp("golden")
    return run_pipeline(
        claim_path=GOLDEN_DIR / "claim.txt",
        out_dir=out_dir,
        write_generator=True,
        example_name="golden_robot_arm",
    )


def test_pipeline_writes_all_outputs(golden_pipeline_run: dict[str, Path]) -> None:
    for key in ("claim_ir", "step", "glb", "claim_map", "generator"):
        path = golden_pipeline_run[key]
        assert path.exists(), f"{key} missing: {path}"
        assert path.stat().st_size > 0, f"{key} is empty: {path}"


def test_pipeline_ir_validates(golden_pipeline_run: dict[str, Path]) -> None:
    raw = golden_pipeline_run["claim_ir"].read_text(encoding="utf-8")
    ir = ClaimIR.model_validate_json(raw)
    # Round-trip
    re_parsed = ClaimIR.model_validate_json(ir.model_dump_json())
    assert re_parsed == ir
    # Golden has 9 components.
    assert len(ir.components) == 9


def test_pipeline_claim_map_matches_ir(golden_pipeline_run: dict[str, Path]) -> None:
    ir = ClaimIR.model_validate_json(golden_pipeline_run["claim_ir"].read_text("utf-8"))
    cmap = json.loads(golden_pipeline_run["claim_map"].read_text("utf-8"))
    assert len(cmap["components"]) == len(ir.components)
    cmap_ids = {row["component_id"] for row in cmap["components"]}
    ir_ids = {c.id for c in ir.components}
    assert cmap_ids == ir_ids


def test_pipeline_glb_node_names_match_components(
    golden_pipeline_run: dict[str, Path],
) -> None:
    """Every root-child GLB node must have a name matching an IR component id."""
    ir = ClaimIR.model_validate_json(golden_pipeline_run["claim_ir"].read_text("utf-8"))
    component_ids = {c.id for c in ir.components}
    glb_names = _glb_root_child_names(golden_pipeline_run["glb"])
    assert glb_names, "GLB has no root children"
    for name in glb_names:
        assert name in component_ids, (
            f"GLB node {name!r} is not an IR component id; "
            f"the GLB renaming step probably failed"
        )


def test_pipeline_step_is_nonempty(golden_pipeline_run: dict[str, Path]) -> None:
    """STEP files start with the ISO-10303 magic line."""
    head = golden_pipeline_run["step"].read_bytes()[:120]
    assert head.startswith(b"ISO-10303-21"), head[:50]


def test_pipeline_step_round_trips_through_build123d(
    golden_pipeline_run: dict[str, Path],
) -> None:
    """The generated STEP must be re-importable by build123d."""
    import build123d as bd

    shape = bd.import_step(str(golden_pipeline_run["step"]))
    bbox = shape.bounding_box()
    assert bbox.size.length > 0


# ---------------------------------------------------------------------------
# Multi-example sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "example_name",
    ["golden_robot_arm", "hinge_assembly", "planetary_gear"],
)
def test_pipeline_runs_each_example(
    example_name: str, tmp_path: Path
) -> None:
    """Run the pipeline against each committed example and check structural
    invariants. This sweep is the Phase-6 regression guard."""
    src = REPO_ROOT / "examples" / example_name / "claim.txt"
    if not src.exists():
        pytest.skip(f"Example {example_name} has no claim.txt")
    out = tmp_path / example_name
    artifacts = run_pipeline(
        claim_path=src,
        out_dir=out,
        write_generator=False,
        example_name=example_name,
    )
    for key in ("claim_ir", "step", "glb", "claim_map"):
        path = artifacts[key]
        assert path.exists() and path.stat().st_size > 0, f"{example_name}/{key} missing"

    ir = ClaimIR.model_validate_json(artifacts["claim_ir"].read_text("utf-8"))
    cmap = json.loads(artifacts["claim_map"].read_text("utf-8"))
    assert len(cmap["components"]) == len(ir.components)
    assert len(ir.components) >= 2

    glb_names = _glb_root_child_names(artifacts["glb"])
    component_ids = {c.id for c in ir.components}
    for name in glb_names:
        assert name in component_ids


def test_manifest_writer_lists_examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`claim2cad.manifest.discover_examples` returns one row per example
    that has all four required artifacts."""
    from claim2cad.manifest import discover_examples

    examples = discover_examples()
    ids = {e.id for e in examples}
    assert "golden_robot_arm" in ids
    # The other two may or may not have artifacts in a fresh checkout; they
    # are present in this run because we generated them in Phase 4 / 5.
    for ex in examples:
        assert ex.glb_path == "model.glb"
        assert ex.ir_path == "claim_ir.json"
