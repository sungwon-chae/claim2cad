# Assembly diagnostics

**collage_score: 0.142** (lower = more coherent)

## Summary

- components: **26**
- centres within 30 mm of origin: **3/26**
- centre spread (stdev mm): X=26.9  Y=19.8  Z=41.4
- pair bbox overlap > 0.10: **2** pairs (0.6%)
- z_separation_score: 0.525  (1.0 = clusters separated, 0.0 = all squeezed together)
- panel_separation_score: 1.000  (1.0 = door + frame on different planes)

## Largest components
| id | size mm | centre mm |
|---|---|---|
| `vehicle_body` | 200×200×8 | (44.9, 30.0, 84.0) |
| `_scaffold_door_panel` | 145×6×191 | (28.6, -30.0, 28.5) |
| `hinge_body_half_assembly` | 63×60×180 | (28.5, 14.0, 84.0) |
| `mounting_wall` | 60×160×3 | (-2.0, 35.0, -36.0) |
| `second_sidewall` | 8×160×40 | (20.4, -25.0, 36.0) |

## High-overlap pairs (Jaccard > 0.5)
(none)

## What a coherent door-hinge assembly looks like

- A door panel and a fixed-frame panel each ≥ 80 mm in two
  axes and ≤ 15 mm thick, on **different planes** (panel_separation ≥ 0.5).
- Two distinct hinge clusters (upper / lower) separated by
  ≥ half the assembly Z range (z_separation ≥ 0.5).
- Most components ≥ 30 mm from origin (central_cluster ≤ 0.4).
- Pairwise bbox overlap < 25 %.

## Per-component centres

| id | centre | size |
|---|---|---|
| `_scaffold_door_panel` | (28.6, -30.0, 28.5) | 145×6×191 |
| `pintle_pin` | (-2.0, 0.0, 36.1) | 10×10×112 |
| `hinge_body_half_assembly` | (28.5, 14.0, 84.0) | 63×60×180 |
| `body_half_sub_assembly` | (53.0, 44.0, 84.0) | 63×80×120 |
| `vehicle_body` | (44.9, 30.0, 84.0) | 200×200×8 |
| `door_half_member` | (89.8, -18.0, 84.0) | 63×40×90 |
| `first_sidewall` | (4.1, -25.0, -9.0) | 8×120×80 |
| `main_member_pintle_pin_hole` | (32.7, 0.0, -21.0) | 8×8×2 |
| `main_member` | (51.2, 12.0, -15.0) | 43×110×90 |
| `leaf_flange_pintle_pin_hole` | (2.0, -30.0, -27.0) | 8×8×2 |
| `u_shaped_link_member` | (4.2, 10.0, -24.0) | 43×35×120 |
| `upper_extension` | (10.2, 8.0, -33.0) | 30×10×25 |
| `leaf_flange` | (-4.1, -22.0, 54.0) | 40×30×25 |
| `base_wall_exterior_guide_surface` | (55.1, 0.0, 51.0) | 8×60×40 |
| `mounting_wall` | (-2.0, 35.0, -36.0) | 60×160×3 |
| `pintle_pin_stop_means` | (2.0, 8.0, 33.0) | 20×8×20 |
| `second_sidewall` | (20.4, -25.0, 36.0) | 8×160×40 |
| `base_wall` | (36.8, 5.0, 33.0) | 40×30×3 |
| `lower_extension` | (47.0, 5.0, 30.0) | 15×8×40 |
| `hinge_axis` | (-2.0, 0.0, -3.0) | 8×8×8 |
| `leg_guide_edge_surface` | (42.9, 0.0, -9.0) | 8×60×40 |
| `lower_leg` | (79.8, 12.0, -12.0) | 43×30×60 |
| `upper_leg` | (61.3, 5.0, -18.0) | 35×10×30 |
| `bight_wall` | (44.9, -30.0, -21.0) | 40×60×30 |
| `stop_means` | (57.2, 15.0, -27.0) | 15×8×12 |
| `link_member_pintle_pin_holes` | (42.9, 0.0, -33.0) | 6×6×2 |
