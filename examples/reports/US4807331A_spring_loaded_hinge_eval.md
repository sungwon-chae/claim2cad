# Evaluation report — US4807331A_spring_loaded_hinge

**Composite score: 0.768**

## Metric breakdown

| metric | score | detail |
|---|---:|---|
| `span_correctness` | 1.000 | n_total=25, n_verified=25, n_bad=0 |
| `glb_coverage` | 1.000 | n_components=25, n_in_glb=25 |
| `figure_callout_coverage` | 0.556 | n_callouts=45, n_bound=25, n_unbound=20 |
| `geometric_invariants` | 0.445 | pin_through_holes=0.0, link_nests_in_main=0.0, door_wraps_assembly=1.0, bbox_sane=0.968, no_obvious_overlap=1.0 |
| `projection_fit` | 0.838 | best_view=front, n_views_rendered=4 |
| `assembly_coherence` | 0.858 | collage_score=0.142, central_cluster_count=3, central_cluster_fraction=0.115, z_separation_score=0.525, panel_separation_score=1.0, pair_overlap_fraction=0.006153846153846154, n_components=26 |
| `projection_anchor_match` | 0.843 | mean_error_mm=7.87, max_error_mm=55.74, n_anchors=25 |
| `central_density` | 0.000 | central_density=0.9566, outer_density=0.0496, ratio=19.3, image=renders_v1.1/figure_aligned_view.png |
| `view_match` | 1.000 | view_kind=isometric, best_view=front |
| `hotspot_grounding` | 0.810 | leader_line_detection_rate=0.95, leader_lines_total=60, leader_lines_detected=57, n_part_hotspots=32, n_label_hotspots=32, hotspot_source_distribution={'leader_endpoint': 31, 'projection_anchor': 1}, leader_grounded_fraction=0.969, duplicate_callout_numbers=15, repeated_instance_count=7, low_confidence_count=0, out_of_bounds_count=0 |

## Notes
(none)

## Visual artifacts
- `figures/figure_1.png`
- `render_comparison.png`
- `renders_v1.1/projection_top.png`
- `renders_v1.1/projection_front.png`
- `renders_v1.1/projection_right.png`
- `renders_v1.1/projection_iso.png`
- `renders_v1.1/leader_line_debug.png`
- `renders_v1.1/figure_hotspot_debug.png`
- `renders_v1.1/figure_hotspot_triplets.png`
