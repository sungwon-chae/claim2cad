"""Build viewer/public/data/manifest.json by enumerating examples/."""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
VIEWER_DATA_DIR = REPO_ROOT / "viewer" / "public" / "data"

# Pretty titles for each known example. Falls back to the directory name.
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


def _required_files(example_dir: Path) -> dict[str, Path]:
    return {
        "claim.txt": example_dir / "claim.txt",
        "claim_ir.json": example_dir / "claim_ir.json",
        "claim_map.json": example_dir / "claim_map.json",
        "model.glb": example_dir / "model.glb",
    }


def discover_examples() -> list[ManifestExample]:
    if not EXAMPLES_DIR.exists():
        return []
    examples: list[ManifestExample] = []
    for child in sorted(EXAMPLES_DIR.iterdir()):
        if not child.is_dir():
            continue
        files = _required_files(child)
        missing = [name for name, path in files.items() if not path.exists()]
        if missing:
            logger.warning("Skipping %s; missing %s", child.name, missing)
            continue
        examples.append(
            ManifestExample(
                id=child.name,
                title=EXAMPLE_TITLES.get(child.name, child.name.replace("_", " ").title()),
                base=child.name,
                claim_text_path="claim.txt",
                ir_path="claim_ir.json",
                claim_map_path="claim_map.json",
                glb_path="model.glb",
            )
        )
    return examples


def stage_for_viewer(*, clean: bool = True) -> Path:
    """Copy each example's four artifacts into ``viewer/public/data/<id>/``."""
    if clean and VIEWER_DATA_DIR.exists():
        shutil.rmtree(VIEWER_DATA_DIR)
    VIEWER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    examples = discover_examples()
    for ex in examples:
        target = VIEWER_DATA_DIR / ex.id
        target.mkdir(parents=True, exist_ok=True)
        src_dir = EXAMPLES_DIR / ex.id
        for filename in (
            ex.claim_text_path,
            ex.ir_path,
            ex.claim_map_path,
            ex.glb_path,
        ):
            shutil.copy2(src_dir / filename, target / filename)
        logger.info("Staged example %s", ex.id)

    manifest = {
        "schema_version": "0.1.0",
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
