# Figure hotspot grounding

The viewer's figure-panel hotspots are part of the
**claim ↔ figure ↔ CAD** contract. Clicking a claim span should
highlight the matching figure region AND the matching 3D mesh, and
vice-versa. Each hotspot is one row of that triplet.

## Coordinate convention (canonical)

Hotspots are stored as **raw image pixel coordinates**, origin
top-left, x grows right, y grows down. The canonical artefact is
``examples/<example>/figure_hotspots.json``:

```json
{
  "schema_version": "0.1.0",
  "figure_id": "figure_1",
  "figure_path": "figures/figure_1.png",
  "image_width_px": 2320,
  "image_height_px": 3408,
  "hotspots": [
    {
      "hotspot_id": "pintle_pin_22",
      "figure_id": "figure_1",
      "component_id": "pintle_pin",
      "callout_number": "22",
      "label": "pintle pin",
      "coord_space": "image_pixel",
      "image_width_px": 2320,
      "image_height_px": 3408,
      "center_px": [690, 645],
      "bbox_px": [596, 528, 784, 762],
      "confidence": 0.85,
      "source": "figure_projection",
      "debug": { "origin": "figure_projection.json component_anchors" }
    }
  ]
}
```

The viewer (``viewer/src/components/FigurePanel.tsx``) reads the
canonical file when it exists and converts to CSS percentages at
render time using ``image_width_px`` / ``image_height_px`` as the
denominator. CSS coordinates are NEVER stored.

## Triplet mapping

```
claim_text span                      figure_1 image                3D CAD mesh
-----------                          --------------                -----------
claim_map.json                       figure_hotspots.json          model_v1.1.glb
  components[i]                        hotspots[j]                   nodes[k]
    .component_id  ────────────────────.component_id  ──────────────.name
    .source_span    (verified by       .center_px      (raw pixels) GLB-naming
                    span_relocator)    .bbox_px                     contract
                                       .callout_number
                                       .source
```

Every link is preserved across the chain:

* `claim span click` →
  `set selectedId = component_id` →
  `<FigurePanel>` filters hotspots by `component_id` and renders
  the selected highlight →
  `<Scene>` recolours the GLB mesh whose name equals
  `component_id`.
* `figure hotspot click` → same `selectedId` → same highlights.
* `CAD mesh click` → same `selectedId` → same highlights.

## Hotspot generation priorities

`claim2cad.figure_hotspots.build_hotspots_for_example` chooses one
position per (component_id, callout_number) pair:

| Priority | Source | When |
|---|---|---|
| 1 | `figure_projection.json` `component_anchors[i].figure_uv` | when the V11-23 figure-projection layout exists. The anchor is the **median** over all label occurrences for the component, which dampens the duplicate-callout-number problem. |
| 2 | median of `figure_map.vlm_labels` whose number maps to this component | when ≥ 2 callouts share a number (figure 1 of US4807331A repeats every callout for upper + lower hinges). |
| 3 | the single `vlm_labels[i].approximate_position` | only one occurrence. |

The chosen source is recorded on the hotspot for audit. The default
viewer marker uses the **part hotspot** (figure_projection or
median); pure label hotspots are flagged so a future overlay can
distinguish them.

## Coordinate transforms — checked at every layer

| Layer | Coordinate space | Tested in |
|---|---|---|
| `figure_map.json` `approximate_position` | normalised [0, 1] over full image | tested via roundtrip |
| `figure_projection.json` `component_anchors[i].figure_uv` | normalised [0, 1] | `tests/test_figure_projection.py::test_world_to_uv_round_trip` |
| `figure_hotspots.json` `center_px` / `bbox_px` | raw image pixels | `tests/test_figure_hotspots.py::test_norm_to_px_centre`, `test_us4807331a_hotspots_in_image_bounds` |
| Viewer CSS `left/top` | percentages of the `<img>` element | computed at render time from raw pixels / `image_width_px` |

## Validation invariants

`claim2cad.figure_hotspots.build_hotspots_for_example` enforces, and
`tests/test_figure_hotspots.py` regresses:

* `0 ≤ center_px.x < image_width_px` and `0 ≤ center_px.y < image_height_px`
* `0 ≤ bbox_px.x0 ≤ x1 ≤ image_width_px`, similarly for y
* `bbox_px` is non-degenerate (`x1 > x0` and `y1 > y0`)
* Every `component_id` exists in `claim_map.json`
* Hotspot UV centres span ≥ 0.20 on each axis (regression check
  against the "all hotspots collapsed to one region" failure mode
  observed in v1.0)

## Known limitations

1. **Leader-line tracing not implemented.** Patent figures use long
   leader lines from numbered labels to the parts they reference.
   We do not trace these; we use the figure-projection median
   instead, which sits closer to the part centroid than the bare
   label position but still inherits some label-vs-part offset for
   isolated callouts.
2. **Per-callout instance disambiguation is heuristic.** When a
   callout number appears in two places (upper hinge + lower hinge
   on US4807331A), the median position lands somewhere between the
   two. A V11-30+ improvement would emit two hotspots — one per
   geographic instance — and link both to the same component_id so
   either one highlights it.
3. **Manual overrides are not supported in the canonical artefact
   today.** Adding a `manual_overrides` block in
   `figure_hotspots.json` is a small forward step when an example
   needs hand-tuned positions.
4. **Generic part-region segmentation is future work.** The right
   long-term answer is a per-part image-segmentation pass that
   produces `bbox_px` over the actual part pixels. v1.1 ships the
   point-anchor approximation.
