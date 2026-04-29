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
      "hotspot_id": "pintle_pin__22__0__part",
      "figure_id": "figure_1",
      "component_id": "pintle_pin",
      "callout_number": "22",
      "label": "pintle pin",
      "coord_space": "image_pixel",
      "image_width_px": 2320,
      "image_height_px": 3408,
      "center_px": [820, 670],
      "bbox_px": [739, 551, 901, 789],
      "confidence": 0.92,
      "source": "leader_endpoint",
      "hotspot_kind": "part",
      "instance_id": 0,
      "label_center_px": [811, 749],
      "label_bbox_px": [762, 712, 860, 786]
    },
    {
      "hotspot_id": "pintle_pin__22__0__label",
      "component_id": "pintle_pin",
      "callout_number": "22",
      "hotspot_kind": "label",
      "instance_id": 0,
      "center_px": [811, 749],
      "bbox_px": [762, 712, 860, 786],
      "source": "label_center"
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
                                       .hotspot_kind  (part | label)
                                       .instance_id   (0, 1, ... per cid)
```

A single component_id can resolve to multiple hotspots when its
callout number repeats in the figure (e.g. upper hinge + lower
hinge on US4807331A). Each occurrence becomes a separate
``instance_id``; selecting any of them highlights the same
``component_id`` mesh.

## Hotspot generation pipeline

V11-34 introduced **leader-line tracing** so part hotspots sit on
the actual part region, not on the digit text:

```
figure_map.json               leader_lines.json (V11-34)         figure_hotspots.json
 .vlm_labels[i]                .leaders[i]                        .hotspots[j]
   .number                       .label_index = i                   .hotspot_id
   .approximate_position ─────►  .label_position_uv ─────────►      .label_center_px
   .description                  .label_bbox_px                     .label_bbox_px
                                 .line_start_px (near label)
                                 .line_end_px   (on the part) ─►   .center_px (part)
                                 .confidence ──────────────────►   .confidence
                                 .method ("hough" | "none")
```

1. **leader_lines.py** — `detect_leaders_for_figure` runs OpenCV's
   probabilistic Hough transform (``HoughLinesP``) over each
   label's local ROI. A candidate segment qualifies when the near
   endpoint sits within ~18 px of the label box, the far endpoint
   is outside the label box, and the segment is at least 30 px
   long. The longest qualifying segment is chosen; its far
   endpoint is the part anchor. No VLM calls.
2. **figure_hotspots.py** — `build_hotspots_for_example` consumes
   the leader records (when present), the figure_projection
   anchors (V11-23), and the raw vlm_labels, in this priority:

| Priority | Source                | When                                                                                                                                    |
| -------: | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
|        1 | `leader_endpoint`     | leader_lines.json provides a `line_end_px` for this label_index                                                                         |
|        2 | `projection_anchor`   | figure_projection.json has a `component_anchors[i].figure_uv` for the cid AND this is the first instance (the projection collapses repeats) |
|        3 | `crop_center`         | reserved — emitted when a per-part image-segmentation crop is available                                                                 |
|        4 | `median_label`        | legacy fallback (median over multiple label occurrences)                                                                                |
|        5 | `label_center`        | last-resort: the digit-text position                                                                                                    |
|        6 | `manual_override`     | reserved — for future hand-tuned overrides                                                                                              |

For every callout instance, `figure_hotspots.json` emits **two**
records: a ``hotspot_kind="part"`` row at the resolved part
anchor (priorities 1–6 above) and a ``hotspot_kind="label"`` row
at the digit text. The viewer always shows the part hotspots; a
"show labels" toggle reveals the label hotspots in a debug
overlay so reviewers can see the leader connection.

## Coordinate transforms — checked at every layer

| Layer                                         | Coordinate space                          | Tested in                                              |
| --------------------------------------------- | ----------------------------------------- | ------------------------------------------------------ |
| `figure_map.json` `approximate_position`      | normalised [0, 1] over full image         | tested via roundtrip                                   |
| `leader_lines.json` `line_end_px`             | raw image pixels                          | `tests/test_leader_lines.py` (visual + bounds checks)  |
| `figure_projection.json` `figure_uv`          | normalised [0, 1]                         | `tests/test_figure_projection.py::test_world_to_uv_round_trip` |
| `figure_hotspots.json` `center_px` / `bbox_px`| raw image pixels                          | `tests/test_figure_hotspots.py`                        |
| Viewer CSS `left/top`                         | percentages of the `<img>` element        | computed at render time from raw pixels / `image_width_px` |

## Validation invariants

`build_hotspots_for_example` enforces, and the eval harness
regresses, the following:

* `0 ≤ center_px.x < image_width_px`, similarly for y.
* `0 ≤ bbox_px.x0 ≤ x1 ≤ image_width_px`, similarly for y.
* `bbox_px` is non-degenerate.
* Every `component_id` exists in `claim_map.json`.
* Hotspot UV centres span ≥ 0.20 on each axis (regression check
  against the "all hotspots collapsed to one region" failure mode).
* `hotspot_kind` ∈ {`part`, `label`}.
* For each `(component_id, hotspot_kind)` pair, `instance_id` is a
  contiguous 0..N sequence.

## Eval metrics (V11-37)

`eval_v11._eval_hotspot_grounding` exposes:

| Metric                          | Definition                                                                  |
| ------------------------------- | --------------------------------------------------------------------------- |
| `leader_line_detection_rate`    | hough hits / total leader candidates                                        |
| `hotspot_source_distribution`   | counts of part hotspots by source                                           |
| `leader_grounded_fraction`      | part hotspots with `source=leader_endpoint` / total part hotspots           |
| `repeated_instance_count`       | # of components with > 1 part hotspot instance                              |
| `low_confidence_count`          | part hotspots with `confidence < 0.5`                                       |
| `out_of_bounds_count`           | part hotspots whose `center_px` is outside the image rectangle              |

Composite hotspot_grounding score:
```
score = 0.6·leader_line_detection_rate
      + 0.3·repeated_instance_score
      + 0.1·in_bounds_score
```
where `repeated_instance_score = min(1, n_repeated_components / n_duplicate_callout_numbers)`
(or 1.0 when the figure has no duplicate callouts).

## Observed numbers — US4807331A_spring_loaded_hinge

| Metric                       | Value      |
| ---------------------------- | ---------: |
| leader_line_detection_rate   | 0.95 (57/60) |
| n_part_hotspots              | 32         |
| leader_grounded_fraction     | 0.97 (31/32) |
| repeated_instance_count      | 7          |
| duplicate_callout_numbers    | ≥ 7        |
| low_confidence_count         | 0          |
| out_of_bounds_count          | 0          |
| **hotspot_grounding score**  | **0.96**   |

Visual artefacts in `renders_v1.1/`:
* `leader_line_debug.png` — green leaders + red boxes for the
  3 callouts where Hough found no segment.
* `figure_hotspot_debug.png` — coloured part markers (green =
  leader_endpoint, blue = projection_anchor, red = label_center)
  with thin connector lines from each label to its part.
* `figure_hotspot_triplets.png` — three-panel visual: figure with
  hotspots, world-XY scatter of CAD anchors, claim text + legend.

## Known limitations / future work

1. **Hough threshold tuning is per-figure-style.** Patents drawn
   with thicker leader strokes or curved leaders may need a
   different ROI radius / min-length / max-gap. The defaults
   target US-style technical drawings.
2. **No per-part image segmentation yet.** `crop_center` is
   reserved for a V11-38+ pass that produces actual per-part bbox
   regions instead of point anchors. Until then the viewer's
   bbox is a fixed-size square around the leader endpoint.
3. **Manual overrides not wired into the canonical artefact.**
   When a hotspot needs a hand-fix, today the only escape hatch is
   patching `figure_hotspots.json` directly. A future
   `figure_hotspots_overrides.json` (read with higher precedence
   than auto-generation) is the clean solution.
4. **Leader association is per-callout, not per-instance.** When a
   callout number repeats AND has multiple leaders in the figure,
   we emit one hotspot per `vlm_labels[i]` entry. If two leaders
   end up at the same `(component_id, callout_number)` they get
   distinct `instance_id`s and both highlight the same part — this
   is correct but the eval doesn't yet verify the geographic
   match (upper-hinge instance vs lower-hinge instance).
