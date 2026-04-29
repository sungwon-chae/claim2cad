# Assembly diagnostics

**collage_score: 0.198** (lower = more coherent)

## Summary

- components: **25**
- centres within 30 mm of origin: **4/25**
- centre spread (stdev mm): X=25.6  Y=17.7  Z=20.6
- pair bbox overlap > 0.10: **27** pairs (9.0%)
- z_separation_score: 0.421  (1.0 = clusters separated, 0.0 = all squeezed together)
- panel_separation_score: 1.000  (1.0 = door + frame on different planes)

## Largest components
| id | size mm | centre mm |
|---|---|---|
| `vehicle_body` | 200×200×8 | (0.0, 80.0, 0.0) |
| `hinge_body_half_assembly` | 63×60×180 | (58.5, 0.0, 0.0) |
| `mounting_wall` | 60×160×3 | (0.0, 30.0, 0.0) |
| `second_sidewall` | 8×160×40 | (20.0, 0.0, 0.0) |
| `body_half_sub_assembly` | 63×80×120 | (58.5, 0.0, 0.0) |

## High-overlap pairs (Jaccard > 0.5)
- `hinge_body_half_assembly` ↔ `body_half_sub_assembly` (jaccard=0.55)

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
| `pintle_pin` | (30.0, 0.0, 3.1) | 10×10×66 |
| `hinge_body_half_assembly` | (58.5, 0.0, 0.0) | 63×60×180 |
| `body_half_sub_assembly` | (58.5, 0.0, 0.0) | 63×80×120 |
| `vehicle_body` | (0.0, 80.0, 0.0) | 200×200×8 |
| `door_half_member` | (58.5, 0.0, 0.0) | 63×40×90 |
| `first_sidewall` | (-40.0, 0.0, 0.0) | 8×120×80 |
| `main_member_pintle_pin_hole` | (30.0, 0.0, 0.0) | 8×8×2 |
| `main_member` | (48.5, 0.0, 0.0) | 43×110×90 |
| `leaf_flange_pintle_pin_hole` | (30.0, 0.0, 55.0) | 8×8×2 |
| `u_shaped_link_member` | (48.5, 0.0, 0.0) | 43×35×120 |
| `upper_extension` | (30.0, 0.0, -7.5) | 30×10×25 |
| `leaf_flange` | (30.0, 0.0, -7.5) | 40×30×25 |
| `base_wall_exterior_guide_surface` | (-30.0, -20.0, 10.0) | 8×60×40 |
| `mounting_wall` | (0.0, 30.0, 0.0) | 60×160×3 |
| `pintle_pin_stop_means` | (30.0, 0.0, 0.0) | 20×8×20 |
| `second_sidewall` | (20.0, 0.0, 0.0) | 8×160×40 |
| `base_wall` | (0.0, 15.0, -20.0) | 40×30×3 |
| `lower_extension` | (30.0, 0.0, -40.0) | 15×8×40 |
| `hinge_axis` | (30.0, 0.0, 0.0) | 8×8×8 |
| `leg_guide_edge_surface` | (20.0, 10.0, 0.0) | 8×60×40 |
| `lower_leg` | (48.5, 0.0, -10.0) | 43×30×60 |
| `upper_leg` | (30.0, 0.0, 25.0) | 35×10×30 |
| `bight_wall` | (20.0, 0.0, 10.0) | 40×60×30 |
| `stop_means` | (-10.0, 0.0, 55.0) | 15×8×12 |
| `link_member_pintle_pin_holes` | (30.0, 0.0, 40.0) | 6×6×2 |
