"""V13-B — HousingPanelScaffold."""
from __future__ import annotations

import build123d as bd

from claim2cad.scaffolds.base import (
    Scaffold, ScaffoldInput, ScaffoldResult, register_scaffold,
)


@register_scaffold
class HousingPanelScaffold(Scaffold):
    """Box / cover / fastener layout."""

    scaffold_id = "housing_panel"

    def build(self, inputs: ScaffoldInput) -> ScaffoldResult:
        cids = inputs.component_ids() or ["component_0"]
        children: list[bd.Part] = []
        ordered: list[str] = []
        for i, cid in enumerate(cids):
            label = inputs.component_label(cid).lower()
            if any(k in label for k in ("housing", "case", "enclosure", "body")):
                solid = bd.Box(120.0, 80.0, 60.0)
            elif any(k in label for k in ("cover", "lid", "top")):
                solid = bd.Box(120.0, 80.0, 6.0).translate((0.0, 0.0, +35.0))
            elif "fastener" in label or "bolt" in label:
                head = bd.Cylinder(radius=2.5, height=2.0).translate((0, 0, 5.0))
                shaft = bd.Cylinder(radius=1.2, height=10.0)
                solid = (head + shaft).translate(
                    (-50.0 + (i * 25.0) % 100.0, 35.0, +35.0))
            elif "port" in label or "opening" in label:
                solid = bd.Cylinder(radius=8.0, height=20.0).translate(
                    (45.0, 30.0, 10.0))
            else:
                solid = bd.Sphere(radius=4.0).translate(
                    (40.0 + (i * 10.0 % 30.0), -30.0,
                     -25.0 + (i // 3) * 20.0))
            solid.label = cid
            children.append(solid); ordered.append(cid)
        compound = bd.Compound(label="assembly", children=children)
        return ScaffoldResult(
            compound=compound, ordered_ids=ordered,
            scaffold_id=self.scaffold_id,
            diagnostics={"n_components": len(cids)},
            quality_tier="partial",
        )
