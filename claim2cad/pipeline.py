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

from claim2cad.claim_hierarchy import filter_ir_to_claim, hierarchy_summary
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
    filter_claim: str | None = None,
    write_hierarchy: bool = True,
) -> dict[str, Path]:
    """Run the full pipeline. Returns a dict of artifact paths.

    ``filter_claim``: when set (e.g. ``"claim_1"`` or ``"1"``), the
    pipeline filters the parsed IR down to that claim and its ancestors
    before exporting CAD. This is the V1-8 multi-claim view.
    ``write_hierarchy``: emit a ``claim_hierarchy.json`` summary alongside
    the IR.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ir, source_label = _load_or_parse(claim_path, ir_path, dry_run=dry_run)
    logger.info("IR ready (%s); %d components", source_label, len(ir.components))

    if filter_claim is not None:
        target = filter_claim if filter_claim.startswith("claim_") else f"claim_{filter_claim}"
        ir = filter_ir_to_claim(ir, target, include_ancestors=True)
        logger.info(
            "Filtered IR to %s (+ ancestors): %d components, %d relations",
            target,
            len(ir.components),
            len(ir.relations),
        )

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

    artifacts: dict[str, Path] = {
        "claim_ir": ir_out,
        "step": cad_paths["step"],
        "glb": cad_paths["glb"],
        "claim_map": map_out,
    }

    if write_hierarchy and len(ir.claims) >= 1:
        hier_path = out_dir / "claim_hierarchy.json"
        hier_path.write_text(
            json.dumps(hierarchy_summary(ir), indent=2) + "\n", encoding="utf-8"
        )
        logger.info("Wrote %s", hier_path)
        artifacts["claim_hierarchy"] = hier_path

    if write_generator:
        gen_path = synthesize_generator(out_dir)
        logger.info("Wrote %s", gen_path)
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
    parser.add_argument(
        "--filter-claim",
        type=str,
        default=None,
        help=(
            "Filter the IR to only the named claim (e.g. '2' or 'claim_2') "
            "and its ancestors before generating CAD. Useful for visualising "
            "what a single dependent claim adds on top of its parent."
        ),
    )
    parser.add_argument(
        "--no-hierarchy",
        action="store_true",
        help="Skip writing claim_hierarchy.json.",
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
            filter_claim=args.filter_claim,
            write_hierarchy=not args.no_hierarchy,
        )
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1

    print(json.dumps({k: str(v) for k, v in artifacts.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
