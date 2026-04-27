# Claim2CAD evaluation report

- Examples evaluated: **5**
- CAD generation success rate: **100%**
- Component (kind) micro-F1: **0.667**
- Component (kind) macro-F1: **0.745**
- Component (ID) micro-F1: **0.860**
- Relation triple micro-F1: **0.444**
- Figure-mapping coverage: **0%**
- Claim→component span coverage: **100%**

## Per-example breakdown

| example | n_comp_act / exp | kind_F1 | rel_F1 | fig_cov | span_cov | step | glb | claims |
|---|---:|---:|---:|---:|---:|:---:|:---:|---:|
| `golden_robot_arm` | 9/9 | 1.000 | 1.000 | 0% | 100% | ✓ | ✓ | 2 |
| `hinge_assembly` | 8/8 | 1.000 | 1.000 | 0% | 100% | ✓ | ✓ | 1 |
| `planetary_gear` | 6/6 | 1.000 | 1.000 | 0% | 100% | ✓ | ✓ | 2 |
| `korean_robot_arm` | 8/6 | 0.545 | 0.000 | 0% | 100% | ✓ | ✓ | 2 |
| `multi_claim_drone` | 9/17 | 0.182 | 0.000 | 0% | 100% | ✓ | ✓ | 5 |
