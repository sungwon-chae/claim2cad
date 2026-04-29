# Assembly diagnostics

**collage_score: 0.059** (lower = more coherent)

## Summary

- components: **26**
- centres within 30 mm of origin: **3/26**
- centre spread (stdev mm): X=64.4  Y=6.7  Z=60.4
- pair bbox overlap > 0.10: **12** pairs (3.7%)
- z_separation_score: 0.972  (1.0 = clusters separated, 0.0 = all squeezed together)
- panel_separation_score: 1.000  (1.0 = door + frame on different planes)

## Largest components
| id | size mm | centre mm |
|---|---|---|
| `_scaffold_door_panel` | 180×6×240 | (-120.0, 0.0, 0.0) |
| `vehicle_body` | 200×200×8 | (60.0, 0.0, 0.0) |
| `pintle_pin` | 10×10×226 | (0.0, 0.0, 3.1) |
| `hinge_body_half_assembly` | 63×60×180 | (28.5, 0.0, 90.0) |
| `mounting_wall` | 60×160×3 | (60.0, 0.0, 0.0) |

## High-overlap pairs (Jaccard > 0.5)
- `base_wall_exterior_guide_surface` ↔ `leg_guide_edge_surface` (jaccard=1.00)
- `upper_extension` ↔ `upper_leg` (jaccard=0.71)
- `main_member_pintle_pin_hole` ↔ `link_member_pintle_pin_holes` (jaccard=0.56)

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
| `_scaffold_door_panel` | (-120.0, 0.0, 0.0) | 180×6×240 |
| `pintle_pin` | (0.0, 0.0, 3.1) | 10×10×226 |
| `hinge_body_half_assembly` | (28.5, 0.0, 90.0) | 63×60×180 |
| `body_half_sub_assembly` | (88.5, 0.0, 0.0) | 63×80×120 |
| `vehicle_body` | (60.0, 0.0, 0.0) | 200×200×8 |
| `door_half_member` | (-91.5, 0.0, 0.0) | 63×40×90 |
| `first_sidewall` | (-120.0, 0.0, 0.0) | 8×120×80 |
| `main_member_pintle_pin_hole` | (0.0, 0.0, 90.0) | 8×8×2 |
| `main_member` | (18.5, 0.0, 90.0) | 43×110×90 |
| `leaf_flange_pintle_pin_hole` | (-120.0, 0.0, 0.0) | 8×8×2 |
| `u_shaped_link_member` | (18.5, 0.0, 90.0) | 43×35×120 |
| `upper_extension` | (0.0, 0.0, 102.0) | 30×10×25 |
| `leaf_flange` | (-132.0, 0.0, 0.0) | 40×30×25 |
| `base_wall_exterior_guide_surface` | (0.0, 0.0, 90.0) | 8×60×40 |
| `mounting_wall` | (60.0, 0.0, 0.0) | 60×160×3 |
| `pintle_pin_stop_means` | (0.0, 0.0, 0.0) | 20×8×20 |
| `second_sidewall` | (-120.0, 0.0, 0.0) | 8×160×40 |
| `base_wall` | (0.0, 0.0, 90.0) | 40×30×3 |
| `lower_extension` | (0.0, 0.0, -106.0) | 15×8×40 |
| `hinge_axis` | (0.0, 0.0, 0.0) | 8×8×8 |
| `leg_guide_edge_surface` | (0.0, 0.0, 90.0) | 8×60×40 |
| `lower_leg` | (18.5, 0.0, -114.0) | 43×30×60 |
| `upper_leg` | (0.0, 0.0, 104.0) | 35×10×30 |
| `bight_wall` | (-120.0, 0.0, 0.0) | 40×60×30 |
| `stop_means` | (0.0, 34.0, 63.0) | 15×8×12 |
| `link_member_pintle_pin_holes` | (0.0, 0.0, 90.0) | 6×6×2 |
