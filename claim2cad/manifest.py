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
}


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


_REQUIRED = ("claim.txt", "claim_ir.json", "claim_map.json", "model.glb")


def _missing(example_dir: Path) -> list[str]:
    return [name for name in _REQUIRED if not (example_dir / name).exists()]


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


def _build_example(example_dir: Path, *, source: str, base_prefix: str = "") -> Optional[ManifestExample]:
    missing = _missing(example_dir)
    if missing:
        logger.warning("Skipping %s; missing %s", example_dir.name, missing)
        return None

    figure_map_path, figure_image_path, coverage = _figure_info(example_dir)
    base = (base_prefix + example_dir.name) if base_prefix else example_dir.name

    tags: list[str] = []
    if coverage >= 0.999:
        tags.append("full_figure_mapping")
    if source == "real_patent":
        tags.append("real_patent")

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


def stage_for_viewer(*, clean: bool = True) -> Path:
    """Copy each example's artefacts into ``viewer/public/data/``."""
    if clean and VIEWER_DATA_DIR.exists():
        shutil.rmtree(VIEWER_DATA_DIR)
    VIEWER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    examples = discover_examples()
    for ex in examples:
        # ``base`` may be ``real_patents/<id>``, mirroring the source layout.
        target = VIEWER_DATA_DIR / ex.base
        target.mkdir(parents=True, exist_ok=True)
        src_dir = (REAL_PATENTS_DIR if ex.source == "real_patent" else EXAMPLES_DIR) / ex.id

        for filename in (ex.claim_text_path, ex.ir_path, ex.claim_map_path, ex.glb_path):
            shutil.copy2(src_dir / filename, target / filename)
        if ex.figure_map_path:
            shutil.copy2(src_dir / ex.figure_map_path, target / ex.figure_map_path)
        if ex.figure_image_path:
            src_img = src_dir / ex.figure_image_path
            dst_img = target / ex.figure_image_path
            dst_img.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_img, dst_img)
        logger.info("Staged %s (source=%s, fig_coverage=%.0f%%)",
                    ex.id, ex.source, ex.figure_coverage * 100)

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
