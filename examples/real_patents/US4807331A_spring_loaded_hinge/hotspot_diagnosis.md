# Figure hotspot diagnosis — US4807331A_spring_loaded_hinge

## Summary

The viewer reads ``figure_map.json``'s `vlm_labels` and renders one
hotspot per labelled callout that maps to a claim component. It uses
`approximate_position` (normalised [0, 1] coordinates) as the
hotspot centre. There are **two real bugs** plus one structural
limitation.

## Coordinate convention currently in use

* `figure_map.vlm_labels[i].approximate_position` is **normalised [0,
  1]** over the FULL image, image origin top-left.
* The viewer renders hotspots in the figure stage with CSS `left =
  position.u * 100 %`, `top = position.v * 100 %`, `width = 5 %`,
  `height = 5 %` (a small fixed square centred on the position).
* `bbox` field is absent from every label in this example.

## Where hotspot positions actually point

Each VLM-detected callout is the **numerical label** (digits like
"22", "100", "39′") drawn in the patent figure. These labels are
connected to the part they reference by a **leader line** that can
be tens to hundreds of pixels long. The current pipeline never
follows the leader; the hotspot ends up over the *number text*, not
over the *part*.

For US4807331A:

* Labels at the top of the figure (`v ≈ 0.22`) carry numbers for
  components that are physically further down the door (the upper
  hinge cluster). The leader lines run from the labels diagonally
  toward parts at `v ≈ 0.30..0.45`. Hotspots placed at the label
  positions land on the **upper margin / column of digits**, not on
  the upper hinge.

## Bug 1 — claim_map.json doesn't carry `figure_number`

The viewer's primary lookup is `claimMapRows.find(r =>
r.figure_number === num)`. None of the 25 rows in
`claim_map.json` have a `figure_number` field, so the primary path
yields zero matches. The fallback path uses `figure_map
.component_to_number` to resolve, which is what we observe today
(viewer says "9 hotspots" because that's how many label positions
match a component AFTER the duplicate-number filter).

## Bug 2 — duplicate callout numbers

15 numbered callouts appear in **two places** in the figure (because
figure 1 shows the same hinge in upper and lower positions on the
door). The viewer renders both. With CSS positioning, two hotspots
share the same `componentId` so highlighting one highlights both
(visually OK), but the user reads it as "the hotspot is in the wrong
place" because at most one of the two positions is the correct
upper-hinge or lower-hinge instance.

## Limitation — label position vs part position

Even after fixing duplicates, putting the hotspot on the **callout
label position** is wrong. The user wants the hotspot on the **part
region** in the figure. We have three sources of information that
together can do better:

1. `figure_map.vlm_labels[i].approximate_position` — label position
   in normalised image coords. Useful when leader-following fails.
2. `figure_projection.json.component_anchors[i].figure_uv` — the
   layout solver's per-component anchor, derived from the median
   callout position assigned to that component. This is closer to
   the part but still inherits the label-vs-part offset.
3. Image-space part bbox — would need leader-line tracing or a
   per-part image-segmentation pass to produce. Not implemented.

## Where the mismatch is introduced

| Stage | Convention used | Mismatch |
|---|---|---|
| Backend `figure_map.json` | normalised [0, 1] over full image | OK in itself, but only the LABEL position |
| Backend `claim_map.json` | no `figure_number` per row | viewer's primary lookup fails |
| Viewer FigurePanel | CSS percentage of `<img>` element | OK if the image's content fills the element (`object-fit: contain` matches `100%/100%` only when aspect matches) |
| Viewer hotspot bbox | hard-coded `5 % × 5 %` square | invisible when component is large |
| Frontend scaling | uses `naturalWidth/naturalHeight` only after onLoad | OK but irrelevant — hotspots are in normalised coords |

## Hotspot table — current vs expected

| component_id | current u, v (label) | expected region | error type |
|---|---|---|---|
| `pintle_pin` | (0.35, 0.22) — top of label column | over the vertical pin between upper & lower hinge | leader-vs-label offset |
| `main_member` | (0.71, 0.26) — number "24" | the upper hinge bracket cluster (~ 0.55, 0.55) | leader-vs-label offset, large |
| `lower_extension` | (0.73, 0.40) | lower bracket leg | smaller error (label nearer part) |
| `upper_extension` | (0.57, 0.30) | upper bracket leg (~ 0.55, 0.45) | leader-vs-label offset |
| `vehicle_body` | (0.72, 0.22) — top label | along the right edge (frame) | OK — labels run along the frame edge |
| `door_half_member` | (0.80, 0.22) — top label | the door panel (left half of figure) | label-vs-part error reversed: figure shows door on the LEFT but its label is at top-right |
| `leaf_flange` | (0.48, 0.32) | small flange on the door, around (0.35, 0.50) | leader-vs-label offset |
| `mounting_wall` | (0.48, 0.35) | back wall of main_member, around (0.55, 0.45) | small offset |
| `pintle_pin_stop_means` | (0.51, 0.39) | head of pintle pin | reasonable |

## What each hotspot SHOULD represent

For a viewer where the user clicks an underlined claim element and
expects the figure highlight to jump to "where the part lives in the
patent drawing", the hotspot should be **the part region** —
typically the centroid of the geometry the leader points at, with a
bbox that covers the part footprint. As a stop-gap when leader
detection isn't available, the **figure_projection layout's
component anchor** is closer to the part than the label position
alone (it averages over multiple callouts pointing at the same
group).

## v11-29..32 plan

1. `claim2cad/figure_hotspots.py` defines a canonical schema with
   raw image-pixel `center_px` and `bbox_px` per hotspot.
2. Generation: prefer the component's `figure_projection`
   anchor (mapped to image pixels via the figure's px size) as the
   part-region centre, fallback to the callout label position.
   Each label's `approximate_position` is also emitted as a
   secondary `label_hotspot` so the user can A/B.
3. Validation: hotspot centre within image bounds, bbox within
   image bounds, every component_id present in claim_map.json,
   upper-hinge components in v < 0.5, lower-hinge in v > 0.5
   (figure-y grows DOWN), no two hotspots within 8 px of each
   other.
4. Viewer reads `figure_hotspots.json` (when present) instead of
   recomputing from `figure_map.vlm_labels`. Falls back to the
   v1.0 path when the file is absent.
5. Tests for crop→full-image, normalised→pixel, schema, and a
   per-region regression fixture for US4807331A.
