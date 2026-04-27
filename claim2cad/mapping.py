"""IR → claim_map.json flattener.

The claim map is the viewer-facing index: one row per component, binding the
IR ``component_id`` to the GLB node name (the same string in our Phase-3
contract) plus enough metadata for the viewer to colour, badge, and tooltip
each row without re-parsing the full IR.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claim2cad.ir_schema import ClaimIR

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class ClaimMap:
    schema_version: str
    example: str
    glb_path: str
    components: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "example": self.example,
            "glb_path": self.glb_path,
            "components": self.components,
        }


def build_claim_map(
    ir: ClaimIR,
    *,
    example_name: str,
    glb_path: str = "model.glb",
) -> ClaimMap:
    rows: list[dict[str, Any]] = []
    for comp in ir.components:
        rows.append(
            {
                "component_id": comp.id,
                "glb_node_name": comp.id,
                "label": comp.label,
                "category": comp.category,
                "kind": comp.kind,
                "is_dependent": comp.is_dependent,
                "source_span": comp.source_span.model_dump(),
            }
        )
    return ClaimMap(
        schema_version=SCHEMA_VERSION,
        example=example_name,
        glb_path=glb_path,
        components=rows,
    )


def write_claim_map(claim_map: ClaimMap, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(claim_map.as_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote %s (%d components)", out_path, len(claim_map.components))
    return out_path


__all__ = ["ClaimMap", "build_claim_map", "write_claim_map"]
