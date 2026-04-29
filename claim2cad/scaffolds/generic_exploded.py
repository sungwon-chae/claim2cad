"""V13-B — GenericExplodedScaffold.

For figures that draw parts spread out along a single axis.
Components arrange in a row by figure_uv ordering.
"""
from __future__ import annotations

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)
from claim2cad.scaffolds.fallback_layout import _build_primitive, _shape_hint


@register_scaffold
class GenericExplodedScaffold(Scaffold):
    """Exploded-along-Z layout. Parts arranged top-to-bottom in
    the order they appear in the claim_map."""

    scaffold_id = "generic_exploded"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        n = len(cids)
        spacing_z = max(40.0, 220.0 / max(n, 1))
        children: list[bd.Part] = []
        ordered: list[str] = []
        for i, cid in enumerate(cids):
            label = inputs.component_label(cid)
            hint = _shape_hint(label)
            try:
                solid = _build_primitive(hint)
            except Exception:  # noqa: BLE001
                solid = bd.Box(20.0, 20.0, 20.0)
            cz = (i - (n - 1) / 2.0) * spacing_z
            cx = 0.0 if i % 2 == 0 else 12.0  # tiny offset to avoid bbox coincidence
            solid = solid.translate((cx, 0.0, cz))
            solid.label = cid
            children.append(solid); ordered.append(cid)
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": n, "spacing_z_mm": round(spacing_z, 1)},
            quality_tier="fallback",
        )
