# V1.4-A — Strict visual quality re-audit

**25 examples.** Strict quality distribution: {'partial': 23, 'fallback': 1, 'flagship': 1}.

Primitive-stack and view-mismatch failures are explicit. An example only earns 'good' if its scaffold uses ≥2 specialized primitives (gear teeth, springs, cams, spokes) and has ≥8 GLB children. Examples whose scaffold is rotary_shaft / bracket_mount / housing_panel / linkage / two_plate_hinge with **no** specialized geometry are downgraded to **partial** until V14-D/E rebuild them with richer primitives.

| ID | topology | scaffold | v1.3 → v1.4 | n_children | specialized | aspect |
|---|---|---|---|---:|---:|---:|
| `US3279624A_unimate_industrial_robot` | robotic_arm | linkage | partial | 8 | 0 | 0.61 |
| `US3705522A_planetary_gear_with_idler` | planetary_gear | planetary_gear | good → **partial** | 12 | 0 | 0.66 |
| `US3789698A_compact_planetary_drive` | rotary_shaft | rotary_shaft | partial | 14 | 0 | 0.71 |
| `US3897696A_harmonic_gear_drive` | harmonic_gear | rotary_shaft | partial | 13 | 0 | 0.70 |
| `US4106366A_automotive_planetary_gearbox` | planetary_gear | rotary_shaft | partial | 5 | 0 | 0.70 |
| `US4196635A_spur_gear_differential` | housing_panel | housing_panel | partial | 13 | 0 | 0.69 |
| `US4329110A_manipulator_with_remote_control` | robotic_arm | linkage | partial | 14 | 1 | 0.76 |
| `US4391163A_planetary_speed_reducer` | planetary_gear | rotary_shaft | partial | 12 | 0 | 0.81 |
| `US4392776A_robotic_hand_with_compliance` | rotary_shaft | rotary_shaft | partial | 13 | 1 | 0.70 |
| `US4407625A_multi_arm_robotic_assembly` | robotic_arm | linkage | partial | 8 | 0 | 0.58 |
| `US4467670A_epicyclic_transmission` | planetary_gear | rotary_shaft | partial | 16 | 0 | 0.84 |
| `US4470181A_self_closing_hinge` | self_closing_hinge_mechanism | self_closing_hinge_mechanism | good → **partial** | 21 | 1 | 0.63 |
| `US4486142A_kuka_articulated_arm` | unknown | fallback_grid | fallback | 7 | 0 | 0.74 |
| `US4502185A_concealed_hinge_assembly` | door_hinge | door_hinge | good → **partial** | 20 | 0 | 0.69 |
| `US4575297A_puma_industrial_robot` | robotic_arm | linkage | partial | 31 | 1 | 0.67 |
| `US4655675A_robotic_assembly_apparatus` | robotic_arm | linkage | partial | 18 | 1 | 0.69 |
| `US4729261A_compact_gear_reduction` | planetary_gear | rotary_shaft | partial | 11 | 0 | 0.85 |
| `US4762016A_robotic_drive_unit` | robotic_arm | linkage | partial | 13 | 0 | 0.62 |
| `US4807331A_spring_loaded_hinge` | door_hinge |  | unknown → **flagship** | 35 | 1 | 0.66 |
| `US4816730A_autonomous_mobile_robot` | robotic_arm | linkage | partial | 12 | 0 | 0.59 |
| `US4856377A_planetary_drive_apparatus` | planetary_gear | rotary_shaft | partial | 17 | 0 | 0.77 |
| `US4955250A_multiple_forearm_robot` | rotary_shaft | rotary_shaft | partial | 13 | 0 | 0.64 |
| `US5042321A_two_stage_planetary_gear` | planetary_gear | rotary_shaft | partial | 11 | 0 | 0.59 |
| `US5180955A_positioning_apparatus_for_arm` | positioning_apparatus | positioning_apparatus | good → **partial** | 25 | 1 | 0.67 |
| `US5239246A_force_reflecting_manipulator` | robotic_arm | linkage | partial | 19 | 0 | 0.61 |

## Cylinder/box-stack failures (downgraded)

* `US3279624A_unimate_industrial_robot` — scaffold `linkage` is primitives-only (8 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US3789698A_compact_planetary_drive` — scaffold `rotary_shaft` is primitives-only (14 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US3897696A_harmonic_gear_drive` — scaffold `rotary_shaft` is primitives-only (13 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4106366A_automotive_planetary_gearbox` — scaffold `rotary_shaft` is primitives-only (5 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4196635A_spur_gear_differential` — scaffold `housing_panel` is primitives-only (13 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4391163A_planetary_speed_reducer` — scaffold `rotary_shaft` is primitives-only (12 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4407625A_multi_arm_robotic_assembly` — scaffold `linkage` is primitives-only (8 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4467670A_epicyclic_transmission` — scaffold `rotary_shaft` is primitives-only (16 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4729261A_compact_gear_reduction` — scaffold `rotary_shaft` is primitives-only (11 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4762016A_robotic_drive_unit` — scaffold `linkage` is primitives-only (13 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4816730A_autonomous_mobile_robot` — scaffold `linkage` is primitives-only (12 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4856377A_planetary_drive_apparatus` — scaffold `rotary_shaft` is primitives-only (17 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US4955250A_multiple_forearm_robot` — scaffold `rotary_shaft` is primitives-only (13 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US5042321A_two_stage_planetary_gear` — scaffold `rotary_shaft` is primitives-only (11 children, all box/cylinder/sphere). Visually a stack, not a mechanism.
* `US5239246A_force_reflecting_manipulator` — scaffold `linkage` is primitives-only (19 children, all box/cylinder/sphere). Visually a stack, not a mechanism.

## View orientation observations

Patent figure aspect ratio ranges:
* 0 wide (>1.4) — likely top/plan/section views.
* 20 tall (<0.75) — likely front/side elevations.
* 5 ~square — likely oblique/multi-view.

These ranges drive V14-B's view classifier and V14-C's camera selection.
