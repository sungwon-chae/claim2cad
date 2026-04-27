"""End-to-end pipeline: claim text → IR → STEP/GLB + claim_map.json.

Single CLI entry point::

    python -m claim2cad.pipeline \\
        --claim examples/golden_robot_arm/claim.txt \\
        --out   examples/golden_robot_arm

Phase 3 ships a deliberately minimal pipeline. The substitutable parts are:

* the parser (``claim2cad.claim_parser.parse_claim``),
* the IR → CAD step (``claim2cad.ir_to_cad.export_cad`` +
  ``synthesize_generator``),
* the mapping writer (``claim2cad.mapping.build_claim_map``).

A future ``--from-ir`` flag is already wired so Phase 4 can skip the parser.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from claim2cad.claim_parser import parse_claim
from claim2cad.ir_schema import ClaimIR
from claim2cad.ir_to_cad import export_cad, synthesize_generator
from claim2cad.mapping import build_claim_map, write_claim_map

logger = logging.getLogger("claim2cad.pipeline")

# Directories the pipeline writes to are caller-supplied; nothing global.


def _load_or_parse(
    claim_path: Path | None,
    ir_path: Path | None,
    *,
    dry_run: bool = False,
) -> tuple[ClaimIR, str]:
    """Return (ir, source_label). source_label is a short human-readable
    description for logging.

    If ``dry_run`` is True and an ``expected_ir.json`` exists next to the
    claim, that file is loaded instead of running the parser. This makes
    CI runs deterministic and free of LLM dependency.
    """
    if ir_path is not None:
        logger.info("Loading IR from %s", ir_path)
        ir = ClaimIR.model_validate_json(ir_path.read_text(encoding="utf-8"))
        return ir, f"loaded from {ir_path.name}"

    if claim_path is None:
        raise ValueError("Either --claim or --from-ir must be provided.")

    if dry_run:
        cached = claim_path.parent / "expected_ir.json"
        if cached.exists():
            logger.info("Dry-run: loading cached IR from %s", cached)
            ir = ClaimIR.model_validate_json(cached.read_text(encoding="utf-8"))
            return ir, f"dry-run cache {cached.name}"
        logger.info("Dry-run: no cached IR; will parse and skip LLM")

    text = claim_path.read_text(encoding="utf-8")
    logger.info("Parsing claim from %s (%d chars)", claim_path, len(text))
    ir = parse_claim(text)
    return ir, f"parsed from {claim_path.name}"


def run_pipeline(
    *,
    claim_path: Path | None,
    out_dir: Path,
    ir_path: Path | None = None,
    write_generator: bool = True,
    example_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Path]:
    """Run the full pipeline. Returns a dict of artifact paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ir, source_label = _load_or_parse(claim_path, ir_path, dry_run=dry_run)
    logger.info("IR ready (%s); %d components", source_label, len(ir.components))

    name = example_name or out_dir.name

    ir_out = out_dir / "claim_ir.json"
    ir_out.write_text(ir.model_dump_json(indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s", ir_out)

    cad_paths = export_cad(ir, out_dir)
    logger.info(
        "Generated CAD: STEP=%s (%d B), GLB=%s (%d B)",
        cad_paths["step"].name,
        cad_paths["step"].stat().st_size,
        cad_paths["glb"].name,
        cad_paths["glb"].stat().st_size,
    )

    claim_map = build_claim_map(ir, example_name=name)
    map_out = out_dir / "claim_map.json"
    write_claim_map(claim_map, map_out)

    if write_generator:
        gen_path = synthesize_generator(out_dir)
        logger.info("Wrote %s", gen_path)

    artifacts: dict[str, Path] = {
        "claim_ir": ir_out,
        "step": cad_paths["step"],
        "glb": cad_paths["glb"],
        "claim_map": map_out,
    }
    if write_generator:
        artifacts["generator"] = out_dir / "pipeline_generator.py"
    return artifacts


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claim2cad",
        description="Patent claim → CAD pipeline.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--claim", type=Path, help="Path to a claim.txt file.")
    src.add_argument(
        "--from-ir",
        dest="ir_path",
        type=Path,
        help="Skip parsing; load this IR JSON instead.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory.")
    parser.add_argument(
        "--example-name",
        type=str,
        default=None,
        help="Override the example name used in claim_map.json (default: out dir name).",
    )
    parser.add_argument(
        "--no-generator",
        action="store_true",
        help="Skip writing generator.py.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Skip the LLM. If an expected_ir.json sits next to claim.txt, "
            "use it; otherwise run the rule-based stub parser only. "
            "Used by CI to keep tests deterministic and offline."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        artifacts = run_pipeline(
            claim_path=args.claim,
            ir_path=args.ir_path,
            out_dir=args.out,
            write_generator=not args.no_generator,
            example_name=args.example_name,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1

    print(json.dumps({k: str(v) for k, v in artifacts.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
