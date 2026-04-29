# Claim2CAD v1.2 evaluation — US4807331A_spring_loaded_hinge

**Composite: 0.662** (verdict: *ok*)

## Visual axes (the human-aligned ones)

| metric | score | detail |
|---|---:|---|
| `figure_resemblance` | 0.016 | rendered_path=renders_v1.2/readable_figure_aligned.png, intersection_pixels=822, union_pixels=51109 |
| `panel_dominance` | 1.000 | panel_pixel_ratio=0.988, full_pixels=49417, panel_pixels=48817 |
| `hinge_axis_visibility` | 1.000 | long_axis_mm=180.0, short_axis_mm=9.0, aspect_ratio=20.0 |
| `floating_components` | 0.556 | n_total=15, n_floating=2 |
| `demo_readability` | 0.616 | verdict=ok, panel_dominance=1.0, n_distinct_large=15, floating_score=0.556 |

## V11 axes (carryover — structural correctness)

V11 composite: **0.768**

| axis | score |
|---|---:|
| `span_correctness` | 1.000 |
| `glb_coverage` | 1.000 |
| `figure_callout_coverage` | 0.556 |
| `geometric_invariants` | 0.445 |
| `projection_fit` | 0.838 |
| `assembly_coherence` | 0.858 |
| `projection_anchor_match` | 0.843 |
| `central_density` | 0.000 |
| `view_match` | 1.000 |
| `hotspot_grounding` | 0.810 |

## Notes
(none)

## Visual artefacts to inspect
- `renders_v1.2/readable_figure_aligned.png`
- `renders_v1.2/readable_iso.png`
- `renders_v1.2/readable_exploded.png`
- `renders_v1.2/solid_comparison.png`
- `renders_v1.2/hotspot_quality_debug.png`
- `renders_v1.2/figure_projection_lock_debug.png`
