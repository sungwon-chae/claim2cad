# Multi-patent audit — V13-A

Programmatic audit of all real-patent examples in `examples/real_patents/`.

Generated 2026-04-29. **25 examples** total.

## Summary

* Topology distribution: {'robotic_arm': 8, 'planetary_gear': 8, 'harmonic_gear': 1, 'differential_gear': 1, 'rotary_shaft': 3, 'door_hinge': 4}
* CAD status: {'v1.0_primitive': 24, 'flagship': 1}
* Hotspot status: {'potentially_recoverable': 23, 'good': 1, 'missing': 1}
* Priority: {'P2': 6, 'P1': 18, 'P0': 1}

Status legend:
* **flagship** — US4807331A; full V1.2 oblique pipeline; hero demo.
* **v1.0_primitive** — has `model.glb` from the v1.0 row-of-primitives builder; no figure-grounded geometry.
* **potentially_recoverable** — figure_map and claim_map are populated; with V1.3 batch we should be able to produce hotspots + a coherent scaffold.

## Per-example breakdown

| ID | Topology | Priority | CAD | Hotspots | n_map | n_callouts | Recommended scaffold |
|---|---|---|---|---|---:|---:|---|
| `US3279624A_unimate_industrial_robot` | robotic_arm | **P2** | v1.0_primitive | potentially_recoverable | 8 | 60 | LinkageScaffold |
| `US3705522A_planetary_gear_with_idler` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 11 | 51 | RotaryShaftScaffold |
| `US3789698A_compact_planetary_drive` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 14 | 60 | RotaryShaftScaffold |
| `US3897696A_harmonic_gear_drive` | harmonic_gear | **P1** | v1.0_primitive | potentially_recoverable | 13 | 14 | RotaryShaftScaffold |
| `US4106366A_automotive_planetary_gearbox` | planetary_gear | **P2** | v1.0_primitive | potentially_recoverable | 5 | 21 | RotaryShaftScaffold |
| `US4196635A_spur_gear_differential` | differential_gear | **P1** | v1.0_primitive | potentially_recoverable | 13 | 37 | RotaryShaftScaffold |
| `US4329110A_manipulator_with_remote_control` | robotic_arm | **P1** | v1.0_primitive | potentially_recoverable | 14 | 50 | LinkageScaffold |
| `US4391163A_planetary_speed_reducer` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 12 | 42 | RotaryShaftScaffold |
| `US4392776A_robotic_hand_with_compliance` | rotary_shaft | **P1** | v1.0_primitive | potentially_recoverable | 13 | 39 | RotaryShaftScaffold |
| `US4407625A_multi_arm_robotic_assembly` | door_hinge | **P2** | v1.0_primitive | potentially_recoverable | 8 | 14 | DoorHingeScaffold |
| `US4467670A_epicyclic_transmission` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 16 | 59 | RotaryShaftScaffold |
| `US4470181A_self_closing_hinge` | door_hinge | **P1** | v1.0_primitive | potentially_recoverable | 14 | 37 | DoorHingeScaffold |
| `US4486142A_kuka_articulated_arm` | robotic_arm | **P2** | v1.0_primitive | potentially_recoverable | 7 | 34 | LinkageScaffold |
| `US4502185A_concealed_hinge_assembly` | door_hinge | **P1** | v1.0_primitive | potentially_recoverable | 12 | 13 | DoorHingeScaffold |
| `US4575297A_puma_industrial_robot` | robotic_arm | **P1** | v1.0_primitive | potentially_recoverable | 31 | 30 | LinkageScaffold |
| `US4655675A_robotic_assembly_apparatus` | robotic_arm | **P1** | v1.0_primitive | potentially_recoverable | 18 | 14 | LinkageScaffold |
| `US4729261A_compact_gear_reduction` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 11 | 38 | RotaryShaftScaffold |
| `US4762016A_robotic_drive_unit` | robotic_arm | **P1** | v1.0_primitive | potentially_recoverable | 13 | 57 | LinkageScaffold |
| `US4807331A_spring_loaded_hinge` | door_hinge | **P0** | flagship | good | 25 | 60 | DoorHingeScaffold |
| `US4816730A_autonomous_mobile_robot` | robotic_arm | **P1** | v1.0_primitive | potentially_recoverable | 12 | 11 | LinkageScaffold |
| `US4856377A_planetary_drive_apparatus` | planetary_gear | **P1** | v1.0_primitive | potentially_recoverable | 17 | 60 | RotaryShaftScaffold |
| `US4955250A_multiple_forearm_robot` | rotary_shaft | **P1** | v1.0_primitive | potentially_recoverable | 13 | 15 | RotaryShaftScaffold |
| `US5042321A_two_stage_planetary_gear` | planetary_gear | **P2** | v1.0_primitive | potentially_recoverable | 11 | 9 | RotaryShaftScaffold |
| `US5180955A_positioning_apparatus_for_arm` | rotary_shaft | **P1** | v1.0_primitive | potentially_recoverable | 19 | 47 | RotaryShaftScaffold |
| `US5239246A_force_reflecting_manipulator` | robotic_arm | **P2** | v1.0_primitive | missing | 19 | 2 | LinkageScaffold |

## Examples by recommended scaffold

### DoorHingeScaffold (4)

* `US4407625A_multi_arm_robotic_assembly` — door_hinge (14 callouts, 8 claim components)
* `US4470181A_self_closing_hinge` — door_hinge (37 callouts, 14 claim components)
* `US4502185A_concealed_hinge_assembly` — door_hinge (13 callouts, 12 claim components)
* `US4807331A_spring_loaded_hinge` — door_hinge (60 callouts, 25 claim components)

### LinkageScaffold (8)

* `US3279624A_unimate_industrial_robot` — robotic_arm (60 callouts, 8 claim components)
* `US4329110A_manipulator_with_remote_control` — robotic_arm (50 callouts, 14 claim components)
* `US4486142A_kuka_articulated_arm` — robotic_arm (34 callouts, 7 claim components)
* `US4575297A_puma_industrial_robot` — robotic_arm (30 callouts, 31 claim components)
* `US4655675A_robotic_assembly_apparatus` — robotic_arm (14 callouts, 18 claim components)
* `US4762016A_robotic_drive_unit` — robotic_arm (57 callouts, 13 claim components)
* `US4816730A_autonomous_mobile_robot` — robotic_arm (11 callouts, 12 claim components)
* `US5239246A_force_reflecting_manipulator` — robotic_arm (2 callouts, 19 claim components)

### RotaryShaftScaffold (13)

* `US3705522A_planetary_gear_with_idler` — planetary_gear (51 callouts, 11 claim components)
* `US3789698A_compact_planetary_drive` — planetary_gear (60 callouts, 14 claim components)
* `US3897696A_harmonic_gear_drive` — harmonic_gear (14 callouts, 13 claim components)
* `US4106366A_automotive_planetary_gearbox` — planetary_gear (21 callouts, 5 claim components)
* `US4196635A_spur_gear_differential` — differential_gear (37 callouts, 13 claim components)
* `US4391163A_planetary_speed_reducer` — planetary_gear (42 callouts, 12 claim components)
* `US4392776A_robotic_hand_with_compliance` — rotary_shaft (39 callouts, 13 claim components)
* `US4467670A_epicyclic_transmission` — planetary_gear (59 callouts, 16 claim components)
* `US4729261A_compact_gear_reduction` — planetary_gear (38 callouts, 11 claim components)
* `US4856377A_planetary_drive_apparatus` — planetary_gear (60 callouts, 17 claim components)
* `US4955250A_multiple_forearm_robot` — rotary_shaft (15 callouts, 13 claim components)
* `US5042321A_two_stage_planetary_gear` — planetary_gear (9 callouts, 11 claim components)
* `US5180955A_positioning_apparatus_for_arm` — rotary_shaft (47 callouts, 19 claim components)

## Honest assessment

Only US4807331A has been polished to flagship quality. Of the other 24 examples:
* All 24 ship with a `model.glb` from the V1.0 primitive builder, which the viewer renders as a row of axis-aligned boxes — recognisable as 'CAD output' but not as the patent figure.
* 23 have figure_map.json with VLM-extracted callouts and claim_map.json with > 5 components, so the V1.3 batch pipeline should be able to:
  - generate canonical figure_hotspots.json (V1.3-F),
  - assign a scaffold template from this audit (V1.3-D),
  - produce model_v1.3.glb that's spatially coherent (V1.3-E).
* Polishing the other examples to flagship quality is OUT OF SCOPE for V1.3. The success bar is: viewer loads, hotspots are within image bounds, components are not all stacked at origin.