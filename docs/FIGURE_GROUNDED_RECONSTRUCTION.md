# Figure-grounded 3D reconstruction (V11-14)

## Why this exists

v1.0 produced topology-correct CAD that didn't look like the patent
figure. v1.1 went through several attempts before landing on a design
that actually delivers genuinely 3D output:

| Pass | Approach | What it produced | Why we moved on |
|---|---|---|---|
| V11-1..5 | Library lookup (Box/Cylinder/Sphere) | a row of generic primitives | the VLM can't override library param defaults reliably |
| V11-6..8 | Library + spatial composer + IR enrichment | a tighter cluster of primitives | composition was the bottleneck, not breadth |
| V11-9 | Patent-family compound (`LiftOffHingeAssembly`) | a coaxial-by-construction hinge | only solves one patent; doesn't generalise |
| V11-10 | CADFusion-style best-of-N + invariants | best of multiple library candidates | hits the same primitive ceiling |
| V11-12 | 2.5D outline-extrusion from figure | flat collage of polygons | flat by construction; no Z layering |
| **V11-14** | **figure_view + shape_inference + assembly_solver** | **real 3D with constraint-driven nesting** | (current) |

## The four modules

### 1. `figure_view_classifier`

One Opus 4.7 vision call per figure that returns:

```json
{
  "view_kind": "isometric",
  "main_axis": "Z",
  "states_shown": ["upper hinge", "lower hinge"],
  "confidence": 0.8,
  "notes": "Perspective view of door frame showing two hinge assemblies."
}
```

Cached to `figure_view.json` so re-runs cost nothing. Drives the
solver's choice of primary extrusion axis.

### 2. `shape_inference`

One vision call per component crop. Returns:

```json
{
  "shape_family": "pin",
  "diameter_mm": 6.0,
  "depth_mm": 90.0,
  "pose_xyz_mm": [0, 0, 0],
  "main_axis": "Z",
  "constraints": [
    {"kind": "coaxial_with", "target": "hinge_axis"},
    {"kind": "passes_through", "target": "main_member_pintle_pin_hole"},
    {"kind": "passes_through", "target": "link_member_pintle_pin_holes"}
  ],
  "confidence": 0.85
}
```

The 16 supported `shape_family` values are tied to a build123d primitive
in `assembly_solver`:

| family | build123d primitive |
|---|---|
| `plate`, `tab`, `flange` | rectangular slab |
| `bracket`, `link`, `housing` | U-channel (base + 2 sides) |
| `hinge_leaf` | plate + barrel knuckle with through-bore |
| `knuckle` | short cylinder with through-hole |
| `pin`, `shaft` | cylinder along main_axis |
| `washer` | annulus |
| `boss` | short cylinder |
| `spring` | helix swept circle |
| `fastener` | shaft + head disc |
| `slot` | thin elongated slab |
| `hole` | annulus marker (placement aid) |
| `other` | fallback small box (flagged in diagnostics) |

The 9 supported `constraint.kind` values:

| kind | enforced by solver |
|---|---|
| `coaxial_with`, `passes_through` | snap dependent's XY to target's XY along shared Z |
| `nested_in` | snap inner part's XY centre to parent's |
| `above`, `below` | Z stack with bbox-aware spacing |
| `attached_to`, `parallel_to`, `perpendicular_to`, `coplanar_with` | recorded for later passes; not yet enforced as hard constraints |

### 3. `assembly_solver`

Three passes:

1. **Pin orientation pass.** Any `pin` / `shaft` whose constraint list
   contains `coaxial_with` / `passes_through` gets its rotation
   reset to (0, 0, 0) and `main_axis` forced to Z, so the cylinder
   stands vertical along the world Z axis.
2. **XY snap pass.** For each `coaxial_with` / `passes_through`
   constraint:
   - if THIS component is a pin/shaft, the TARGET snaps to it
     (carrying the rest of the dependents along);
   - else THIS component's XY snaps to the target's XY (the pin).
3. **Z stacking pass.** `above` / `below` constraints place the
   dependent at `target.z ± (target_h + own_h) / 2`.

The result is a flat `bd.Compound` with one labelled top-level child
per component_id. The GLB-naming postprocess preserves every
component_id as a viewer-selectable mesh.

### 4. `projection_compare`

Renders top/front/right/iso views via the V11-10 engineering-drawing
renderer (silhouette + 32° crease only) and scores each view by
silhouette aspect-ratio match against the patent figure. The best
view is recorded in `projection_report.json`:

```json
{
  "best_view": "top",
  "best_aspect_score": 0.869,
  "views": [
    {"name": "top", "aspect_ratio": 1.4, "silhouette_area_ratio": 0.18, ...},
    ...
  ]
}
```

The viewer reads this on example load and highlights the best preset
button (green border + ★ badge).

## End-to-end on US4807331A

```
$ python -m claim2cad.figure_to_cad \
    examples/real_patents/US4807331A_spring_loaded_hinge \
    --mode 3d --figure-scale-mm 200

INFO ... figure_view_classify (cached) → isometric, main_axis=Z
INFO ... shape_inference 25/25 (cached)
INFO ... assembly_solver: 25 components placed
INFO ... GLB renamed 25 root children (matches claim_map)
INFO ... projection_compare best=top score=0.869

$ python -m claim2cad.eval_v11 \
    examples/real_patents/US4807331A_spring_loaded_hinge

span_correctness        1.000
glb_coverage            1.000
figure_callout_coverage 0.556
geometric_invariants    0.730
projection_fit          0.869
composite               0.882
```

## Cost

| Stage | Cost (cached run) | Cost (cold run) |
|---|---:|---:|
| `figure_view_classify` | $0 | ~$0.03 |
| `figure_crops` | $0 | $0 |
| `shape_inference` | $0 | ~$0.03 × N components |
| `assembly_solver` | $0 | $0 |
| `projection_compare` | $0 | $0 |
| `eval_v11` | $0 | $0 |

For US4807331A (25 components): cold ~$0.85, cached $0.

## Failure modes

* **`shape_family: "other"`** — VLM didn't recognise the part. The
  solver builds a small box and flags `fell_back_to_box=True` in
  `solver_diagnostics.json`. About 5/25 components on US4807331A
  end up here (the abstract IR concepts: hinge_axis, body_half_sub
  -assembly, vehicle_body, leg_guide_edge_surface, base_wall_exterior_
  guide_surface).
* **No `passes_through` from a pin** — `pin_through_holes` invariant
  scores low. The solver still places parts; it just can't snap
  alignment.
* **Constraint cycle** — solver does a single pass, so `A above B`
  and `B above A` both land at their VLM poses. Not yet detected.
* **VLM dimension ambiguity** — shape_inference can produce a
  90 mm-long pin with a 50 mm-long bracket, or vice versa, depending
  on how it reads the figure. The `figure_scale_mm` CLI flag clamps
  the global scale.

## When to use which mode

| `--mode` | When |
|---|---|
| `3d` (default) | A figure is available and you want figure-grounded reconstruction. |
| `outline` | A figure is available, you want pure 2D-extrusion (e.g. flat layout diagrams). |
| `library` | No figure or you want the legacy library/codegen path. |
