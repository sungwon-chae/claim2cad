"""IR → claim_map.json flattener.

The claim map is the viewer-facing index: one row per component, binding the
IR ``component_id`` to the GLB node name (the same string in our Phase-3
contract) plus enough metadata for the viewer to colour, badge, and tooltip
each row without re-parsing the full IR.

V11-13 adds a span-relocation pass: LLM-emitted source_span offsets drift
cumulatively (off by N chars on the Nth component), which broke claim-text
underlines in the viewer. We re-locate each component's span by searching
its label in the claim text directly, with token-set fallback for
coordinated patent forms ("upper and lower parallel extensions"). Each
claim_map row gets a ``span_verified`` flag so the viewer can hide the
underline when the relocation could not find a confident match.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claim2cad.ir_schema import ClaimIR
from claim2cad.span_relocator import relocate_components, write_span_debug

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.2.0"


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
    span_debug_path: Path | None = None,
) -> ClaimMap:
    """Build the viewer-facing claim_map.

    The LLM offsets in ``ir.components[*].source_span`` are not trusted;
    we re-locate each component's span by searching for its label in
    the claim text. Verified spans go into the claim_map; unverified
    spans still appear (so row-based selection works) but flagged
    ``span_verified=False`` so the viewer can hide the underline rather
    than highlight nonsense.
    """
    claims_text_by_id = {c.id: c.text for c in ir.claims}
    component_dicts = [
        {
            "id": comp.id,
            "label": comp.label,
            "source_span": comp.source_span.model_dump(),
        }
        for comp in ir.components
    ]
    relocated = relocate_components(
        claims_text_by_id=claims_text_by_id,
        components=component_dicts,
    )
    relocated_by_id = {r.component_id: r for r in relocated}
    if span_debug_path is not None:
        try:
            write_span_debug(relocated, component_dicts, span_debug_path)
        except Exception as exc:  # noqa: BLE001 — diagnostics are best effort
            logger.warning("Could not write span_debug to %s: %s", span_debug_path, exc)

    rows: list[dict[str, Any]] = []
    for comp in ir.components:
        r = relocated_by_id.get(comp.id)
        if r is not None and r.verified:
            span: dict[str, Any] = {
                "claim_id": r.claim_id,
                "char_start": r.char_start,
                "char_end": r.char_end,
            }
            extracted = r.extracted
            verified = True
            matched_key = r.matched_key
        else:
            # Fall back to the original span but mark unverified so the
            # viewer doesn't underline a wrong substring.
            span = comp.source_span.model_dump()
            extracted = ""
            verified = False
            matched_key = ""
        rows.append(
            {
                "component_id": comp.id,
                "glb_node_name": comp.id,
                "label": comp.label,
                "category": comp.category,
                "kind": comp.kind,
                "is_dependent": comp.is_dependent,
                "source_span": span,
                "span_verified": verified,
                "span_extracted": extracted,
                "span_match_key": matched_key,
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
