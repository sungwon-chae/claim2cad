"""Build viewer/public/data/manifest.json by enumerating examples/.

Discovers two example sources:

1. Top-level synthetic examples (`examples/golden_robot_arm`, etc).
2. Real patents under `examples/real_patents/<id>_<slug>/`.

Each example with all required files (claim.txt, claim_ir.json,
claim_map.json, model.glb) is staged into `viewer/public/data/<id>/`. If
a `figure_map.json` and primary figure image are present, those are also
copied and surfaced in the manifest entry.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
REAL_PATENTS_DIR = EXAMPLES_DIR / "real_patents"
VIEWER_DATA_DIR = REPO_ROOT / "viewer" / "public" / "data"

# Pretty titles for known synthetic examples; real patents fall back to the
# patent title from source_metadata.json.
EXAMPLE_TITLES = {
    "golden_robot_arm": "Articulated Robotic Manipulator (golden)",
    "hinge_assembly": "Four-Bar Linkage / Hinge Assembly",
    "planetary_gear": "Planetary Gear Assembly",
    "korean_robot_arm": "로봇 매니퓰레이터 (Korean robot arm)",
    "multi_claim_drone": "Quadrotor Drone (5-claim hierarchy)",
}


@dataclass
class DiffSummary:
    comparison_id: str
    comparison_title: str
    diff_path: str  # filename relative to the example's staged directory
    matched: int = 0
    novel_in_base: int = 0
    only_in_comparison: int = 0


@dataclass
class ManifestExample:
    id: str
    title: str
    base: str
    claim_text_path: str
    ir_path: str
    claim_map_path: str
    glb_path: str
    # V1-3 / V1-4 additions:
    figure_map_path: Optional[str] = None
    figure_image_path: Optional[str] = None
    figure_coverage: float = 0.0  # fraction of components mapped to a figure number
    source: str = "synthetic"   # "synthetic" | "real_patent" | "korean"
    tags: list[str] = field(default_factory=list)
    # V1-5 additions:
    diffs_available: list[DiffSummary] = field(default_factory=list)
    # V1-6 additions:
    urdf_path: Optional[str] = None
    movable_joints: list[str] = field(default_factory=list)
    # V1-8 additions:
    n_claims: int = 1
    n_dependent_claims: int = 0
    max_claim_depth: int = 1
    claim_hierarchy_path: Optional[str] = None


_REQUIRED = ("claim.txt", "claim_ir.json", "claim_map.json", "model.glb")


def _missing(example_dir: Path) -> list[str]:
    return [name for name in _REQUIRED if not (example_dir / name).exists()]


def _preferred_glb(example_dir: Path) -> str:
    """Return the GLB filename to ship to the viewer for ``example_dir``.

    v1.1 introduced ``model_v1.1.glb`` as the figure-driven CAD output.
    When present we prefer it over the v1.0 ``model.glb`` so the viewer at
    ``localhost:4179`` shows the v1.1 quality where it exists, and the
    v1.0 row-of-primitives where v1.1 hasn't been run yet.
    """
    if (example_dir / "model_v1.1.glb").exists():
        return "model_v1.1.glb"
    return "model.glb"


def _figure_info(example_dir: Path) -> tuple[Optional[str], Optional[str], float]:
    """Return (figure_map_path, figure_image_path, coverage) for ``example_dir``."""
    fmap_path = example_dir / "figure_map.json"
    if not fmap_path.exists():
        return None, None, 0.0
    try:
        fmap = json.loads(fmap_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None, 0.0
    primary = fmap.get("primary_figure") or ""
    image_path: Optional[str] = None
    if primary:
        candidate = example_dir / "figures" / primary
        if candidate.exists():
            image_path = f"figures/{primary}"
    n_mapped = len(fmap.get("component_to_number", {}) or {})
    ir_path = example_dir / "claim_ir.json"
    n_components = 1
    if ir_path.exists():
        try:
            ir = json.loads(ir_path.read_text(encoding="utf-8"))
            n_components = max(1, len(ir.get("components", [])))
        except json.JSONDecodeError:
            pass
    coverage = round(n_mapped / n_components, 3)
    return "figure_map.json", image_path, coverage


def _title_from_metadata(example_dir: Path, fallback_id: str) -> str:
    meta_path = example_dir / "source_metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = meta.get("title")
            if title:
                pid = meta.get("patent_id", "")
                return f"{pid} — {title}".strip(" —")
        except json.JSONDecodeError:
            pass
    return EXAMPLE_TITLES.get(fallback_id, fallback_id.replace("_", " ").title())


def _diffs_in(example_dir: Path) -> list[tuple[str, str]]:
    """Return list of (comparison_id, diff_filename) for every
    ``diff_<id>.json`` in the example dir."""
    out: list[tuple[str, str]] = []
    for child in sorted(example_dir.glob("diff_*.json")):
        cid = child.stem[len("diff_"):]
        out.append((cid, child.name))
    return out


def _urdf_info(example_dir: Path) -> tuple[Optional[str], list[str]]:
    """Return (urdf_path, movable_joint_names)."""
    urdf = example_dir / "model.urdf"
    if not urdf.exists():
        return None, []
    import re as _re
    text = urdf.read_text(encoding="utf-8")
    movable = _re.findall(
        r'<joint\s+name="([^"]+)"\s+type="(?:revolute|prismatic|continuous)"',
        text,
    )
    return "model.urdf", movable


def _build_example(example_dir: Path, *, source: str, base_prefix: str = "") -> Optional[ManifestExample]:
    missing = _missing(example_dir)
    if missing:
        logger.warning("Skipping %s; missing %s", example_dir.name, missing)
        return None

    figure_map_path, figure_image_path, coverage = _figure_info(example_dir)
    urdf_path, movable_joints = _urdf_info(example_dir)
    base = (base_prefix + example_dir.name) if base_prefix else example_dir.name

    tags: list[str] = []
    if coverage >= 0.999:
        tags.append("full_figure_mapping")
    if source == "real_patent":
        tags.append("real_patent")
    if movable_joints:
        tags.append("kinematic")

    # V1-7: detect Korean claims and tag them.
    try:
        from claim2cad.lang import detect_language
        claim_text = (example_dir / "claim.txt").read_text(encoding="utf-8")
        if detect_language(claim_text) == "ko":
            tags.append("korean")
            if source == "synthetic":
                source = "korean"
    except Exception:  # pragma: no cover — defensive
        pass

    # V1-8: claim hierarchy info. Compute from the IR rather than reading
    # claim_hierarchy.json (which is optional).
    n_claims = 1
    n_dependent_claims = 0
    max_claim_depth = 1
    claim_hierarchy_path: Optional[str] = None
    try:
        from claim2cad.claim_hierarchy import hierarchy_summary
        from claim2cad.ir_schema import ClaimIR
        ir_text = (example_dir / "claim_ir.json").read_text(encoding="utf-8")
        ir_obj = ClaimIR.model_validate_json(ir_text)
        summary = hierarchy_summary(ir_obj)
        n_claims = len(summary["claims"])
        n_dependent_claims = summary["n_dependent"]
        max_claim_depth = summary["max_depth"]
        if n_dependent_claims > 0:
            tags.append("multi_claim")
        if (example_dir / "claim_hierarchy.json").exists():
            claim_hierarchy_path = "claim_hierarchy.json"
    except Exception:  # pragma: no cover — defensive
        pass

    # The viewer always loads ``model.glb`` from the staged dir; we choose
    # which source GLB to copy under that name (v1.1 if present, else v1.0)
    # and tag the example so the UI can surface "v1.1 figure-driven CAD"
    # next to the older primitive-CAD examples.
    if (example_dir / "model_v1.1.glb").exists():
        tags.append("v1.1_cad")
    return ManifestExample(
        id=example_dir.name,
        title=_title_from_metadata(example_dir, example_dir.name),
        base=base,
        claim_text_path="claim.txt",
        ir_path="claim_ir.json",
        claim_map_path="claim_map.json",
        glb_path="model.glb",
        figure_map_path=figure_map_path,
        figure_image_path=figure_image_path,
        figure_coverage=coverage,
        source=source,
        tags=tags,
        diffs_available=[],  # populated by _populate_diffs() below
        urdf_path=urdf_path,
        movable_joints=movable_joints,
        n_claims=n_claims,
        n_dependent_claims=n_dependent_claims,
        max_claim_depth=max_claim_depth,
        claim_hierarchy_path=claim_hierarchy_path,
    )


def discover_examples() -> list[ManifestExample]:
    examples: list[ManifestExample] = []

    # 1. Synthetic top-level examples (golden_robot_arm, hinge_assembly, ...).
    for child in sorted(EXAMPLES_DIR.iterdir()):
        if not child.is_dir() or child.name == "real_patents":
            continue
        ex = _build_example(child, source="synthetic")
        if ex is not None:
            examples.append(ex)

    # 2. Real patents.
    if REAL_PATENTS_DIR.exists():
        for child in sorted(REAL_PATENTS_DIR.iterdir()):
            if not child.is_dir():
                continue
            ex = _build_example(child, source="real_patent", base_prefix="real_patents/")
            if ex is not None:
                examples.append(ex)

    return examples


def _populate_diffs(examples: list[ManifestExample]) -> None:
    """Fill in ``diffs_available`` for each example by scanning for
    ``diff_<id>.json`` files. Each diff is paired with the manifest entry
    of its comparison (if it's a known example), so the viewer can show
    a friendly title."""
    by_id = {e.id: e for e in examples}
    for ex in examples:
        src_dir = _src_dir_for(ex)
        if not src_dir.exists():
            continue
        for cid, filename in _diffs_in(src_dir):
            diff = json.loads((src_dir / filename).read_text(encoding="utf-8"))
            comparison_title = (
                by_id[cid].title if cid in by_id else cid.replace("_", " ")
            )
            ex.diffs_available.append(DiffSummary(
                comparison_id=cid,
                comparison_title=comparison_title,
                diff_path=filename,
                matched=len(diff.get("matched", [])),
                novel_in_base=len(diff.get("novel_in_base", [])),
                only_in_comparison=len(diff.get("only_in_comparison", [])),
            ))


def _src_dir_for(ex: ManifestExample) -> Path:
    if ex.source == "real_patent":
        return REAL_PATENTS_DIR / ex.id
    return EXAMPLES_DIR / ex.id


def stage_for_viewer(*, clean: bool = True) -> Path:
    """Copy each example's artefacts into ``viewer/public/data/``."""
    if clean and VIEWER_DATA_DIR.exists():
        shutil.rmtree(VIEWER_DATA_DIR)
    VIEWER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    examples = discover_examples()
    _populate_diffs(examples)
    for ex in examples:
        # ``base`` may be ``real_patents/<id>``, mirroring the source layout.
        target = VIEWER_DATA_DIR / ex.base
        target.mkdir(parents=True, exist_ok=True)
        src_dir = _src_dir_for(ex)

        for filename in (ex.claim_text_path, ex.ir_path, ex.claim_map_path):
            shutil.copy2(src_dir / filename, target / filename)
        # Stage the chosen source GLB under the canonical name ``model.glb``.
        # If model_v1.1.glb exists in the source we ship that — the viewer
        # codepath is unchanged.
        source_glb = src_dir / _preferred_glb(src_dir)
        shutil.copy2(source_glb, target / "model.glb")
        # V11-15: stage optional v1.1 sidecars (best-effort) so the viewer
        # can show camera presets / shape metadata when present.
        for optional in (
            "projection_report.json",
            "figure_view.json",
            "shape_inference.json",
            "solver_diagnostics.json",
            "scene_scaffold.json",
            "assembly_diagnostics.json",
            "render_comparison.png",
        ):
            src_p = src_dir / optional
            if src_p.exists():
                shutil.copy2(src_p, target / optional)
        if ex.figure_map_path:
            shutil.copy2(src_dir / ex.figure_map_path, target / ex.figure_map_path)
        if ex.claim_hierarchy_path:
            shutil.copy2(src_dir / ex.claim_hierarchy_path, target / ex.claim_hierarchy_path)
        if ex.figure_image_path:
            src_img = src_dir / ex.figure_image_path
            dst_img = target / ex.figure_image_path
            dst_img.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_img, dst_img)
        for ds in ex.diffs_available:
            shutil.copy2(src_dir / ds.diff_path, target / ds.diff_path)
        if ex.urdf_path:
            shutil.copy2(src_dir / ex.urdf_path, target / ex.urdf_path)
        logger.info("Staged %s (source=%s, fig_coverage=%.0f%%, diffs=%d, movable=%d)",
                    ex.id, ex.source, ex.figure_coverage * 100,
                    len(ex.diffs_available), len(ex.movable_joints))

    manifest = {
        "schema_version": "0.2.0",
        "examples": [asdict(e) for e in examples],
    }
    manifest_path = VIEWER_DATA_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s with %d examples", manifest_path, len(examples))
    return manifest_path


def main() -> int:
    logging.getLogger("claim2cad").setLevel(logging.INFO)
    stage_for_viewer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
