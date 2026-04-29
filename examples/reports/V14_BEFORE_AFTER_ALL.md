# V1.4 — before/after corpus table

v1.3 quality is from MULTI_PATENT_EVAL (eval_v13).
v1.4 quality is from V14_QUALITY_TABLE (eval_v14, strict).

Quality migration:

* `partial → partial` — 13 examples
* `partial → good` — 5 examples
* `good → good` — 4 examples
* `fallback → good` — 1 examples
* `fallback → fallback` — 1 examples
* `flagship → flagship` — 1 examples

| ID | topology | scaffold | v1.3 | v1.4 | score | flags |
|---|---|---|---|---|---:|---|
| `US3279624A_unimate_industrial_robot` | robotic_arm | linkage | partial | **partial** | 0.98 | - |
| `US3705522A_planetary_gear_with_idler` | planetary_gear | planetary_gear | good | **good** | 1.00 | - |
| `US3789698A_compact_planetary_drive` | rotary_shaft | rotary_shaft | partial | **partial** | 1.00 | - |
| `US3897696A_harmonic_gear_drive` | harmonic_gear | rotary_shaft | partial | **partial** | 0.93 | - |
| `US4106366A_automotive_planetary_gearbox` | planetary_gear | planetary_gear | fallback | **good** | 1.00 | - |
| `US4196635A_spur_gear_differential` | housing_panel | housing_panel | partial | **partial** | 1.00 | - |
| `US4329110A_manipulator_with_remote_control` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4391163A_planetary_speed_reducer` | planetary_gear | planetary_gear | partial | **good** | 1.00 | - |
| `US4392776A_robotic_hand_with_compliance` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4407625A_multi_arm_robotic_assembly` | robotic_arm | linkage | partial | **partial** | 0.98 | - |
| `US4467670A_epicyclic_transmission` | planetary_gear | planetary_gear | partial | **good** | 1.00 | - |
| `US4470181A_self_closing_hinge` | self_closing_hinge_mechanism | self_closing_hinge_mechanism | good | **good** | 1.00 | - |
| `US4486142A_kuka_articulated_arm` | unknown | fallback_grid | fallback | **fallback** | 0.62 | - |
| `US4502185A_concealed_hinge_assembly` | two_plate_hinge | two_plate_hinge | good | **good** | 1.00 | - |
| `US4575297A_puma_industrial_robot` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4655675A_robotic_assembly_apparatus` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4729261A_compact_gear_reduction` | planetary_gear | planetary_gear | partial | **good** | 1.00 | - |
| `US4762016A_robotic_drive_unit` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4807331A_spring_loaded_hinge` | door_hinge |  | flagship | **flagship** | 0.72 | - |
| `US4816730A_autonomous_mobile_robot` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US4856377A_planetary_drive_apparatus` | planetary_gear | planetary_gear | partial | **good** | 1.00 | - |
| `US4955250A_multiple_forearm_robot` | robotic_arm | linkage | partial | **partial** | 1.00 | - |
| `US5042321A_two_stage_planetary_gear` | planetary_gear | planetary_gear | partial | **good** | 1.00 | - |
| `US5180955A_positioning_apparatus_for_arm` | positioning_apparatus | positioning_apparatus | good | **good** | 1.00 | - |
| `US5239246A_force_reflecting_manipulator` | robotic_arm | linkage | partial | **partial** | 1.00 | - |