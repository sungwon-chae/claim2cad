# Refinement Log — US4807331A_spring_loaded_hinge

**Promoted iteration:** 00 (best score 3.0/10).
**Stopped:** `max_iterations 2`. Last iteration score 2.0/10 (regression vs. iter00 — see "Refinement instability" below).

## Iterations

| iter | score | sil | prop | feat | arr | defects | refined-for-next-iter | cost $ |
|----:|------:|----:|----:|----:|----:|--------:|----------------------|------:|
| 00 | **3.0** | 3.0 | 4.0 | 2.0 | 3.0 | 7 | u_shaped_link_member, door_half_member, main_member, upper_leg, pintle_pin | 7.274 |
| 01 | 2.0 | 2.0 | 2.0 | 1.0 | 2.0 | 6 | u_shaped_link_member, door_half_member, body_half_sub_assembly, pintle_pin, vehicle_body | 7.360 |
| 02 | 2.0 | 2.0 | 3.0 | 2.0 | 2.0 | 7 | (max iters reached) | 7.451 |

(`refined-for-next-iter` = components the VLM rewrote at the end of that
iteration, which became the input to the next one. The "cost" column is
cumulative session cost up to that validation call.)

## Why iter00 won

iter00 — the assembly built straight from V11-3's figure_spec.json — scored
3/10. The VLM's review identified five components needing rework
(u_shaped_link_member, door_half_member, main_member, upper_leg,
pintle_pin) and proposed revised positions/dimensions. The revisions
made the assembly worse: iter01 dropped to 2/10, and the loop halted at
iter02 after two consecutive non-improving steps.

This is the right behavior: V11-4's loop is allowed to regress, and the
canonical model_v1.1.* paths are promoted from the **best** iteration,
not the last. iter00's STEP and GLB were copied to model_v1.1.step /
model_v1.1.glb after the loop finished.

## iter00 defects (the issues that drove the refinement attempt)

Reproduced from the iter00 SimilarityReport stored in
`refinement_summary.json`:

> The CAD captures only the broadest arrangement: a mounting plate with a
> small hinge block and a perpendicular plate. Almost none of the
> distinctive hinge geometry — U-shaped link, parallel extensions, leaf
> flange, pintle pin with stops — is visible, so the model reads as a
> placeholder rather than a faithful depiction.

Defects targeted by the failed refinement:

- `u_shaped_link_member` — U-bracket placed but oriented so the U opening
  is not visible from the iso/front views.
- `door_half_member` — placed as a flat plate, lacks the channel (bight
  wall + sidewalls) called out by the claim.
- `main_member` — instantiated as a plate, lacks the upper/lower
  extensions + mounting wall structure.
- `upper_leg` — missing characteristic guide-edge surfaces.
- `pintle_pin` — placed but not vertically aligned through both the U-bracket
  and the leaf-flange holes.

## Refinement instability

The loop has a known failure mode: when the VLM proposes new
position_mm or rotation_deg values for a component, those changes can
break alignment with neighbouring components that were not flagged. The
VLM scores the next iteration globally, which means a small local
improvement can be wiped out by an arrangement regression.

What we shipped to mitigate it:

1. Track the best-scoring iteration and promote IT to the canonical
   model_v1.1.* paths.
2. Halt the loop after two consecutive non-improving iterations
   (avoid burning more vision-call budget on a doom spiral).

What this loop still needs (Session 2 work):

3. **Per-component rendering** instead of whole-assembly rendering — a
   crop around the component lets the VLM judge it in isolation.
4. **Constraint-aware revisions** — the VLM should be told which
   components it must NOT move (so it can refine a leaf without
   shifting the pin axis it shares with another leaf).
5. **Multi-figure context** — feeding figures 2 and 3 alongside figure 1
   would help the VLM understand the lifted-off state, which the current
   single-figure prompt cannot resolve.

## Final defects (iter02 — for comparison)

These are the defects flagged on the iter02 model, which we did NOT
ship. They overlap heavily with iter00's defects, confirming that the
refinement loop did not address the root issues.

- **[major]** `u_shaped_link_member` — No recognizable U-shape with upper/lower parallel legs visible.
- **[major]** `main_member` — Main member lacks the characteristic bracket with upper/lower extensions and mounting wall.
- **[major]** `door_half_member` — Leaf flange with pintle pin hole not clearly represented.
- **[major]** `pintle_pin` — Pintle pin appears as a thin stub rather than vertical pin through aligned holes.
- **[major]** `hinge_axis` — No clear vertical hinge axis arrangement; components appear as blocky slabs.
- **[moderate]** `vehicle_body` — Only a flat plate shown; lacks the body panel context.
- **[moderate]** `stop_means` — Stop features not identifiable.
