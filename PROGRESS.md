# Claim2CAD — Progress Log

A timestamped, phase-by-phase log of what was done, what was verified, and what
was deferred. Times are local (Asia/Seoul, KST).

---

## Phase 1 — Reconnaissance — STARTED 2026-04-27 00:45 KST

### Setup
- Initial `git clone https://github.com/earthtojake/text-to-cad` aborted with
  `HTTP/2 stream cancel` mid-fetch. Re-cloned with HTTP/1.1 + larger
  `http.postBuffer` and `--depth=1`; succeeded.
- Per the user's clarification, the upstream `text-to-cad/` checkout is held
  read-only as a *reference*. Claim2CAD lives in a sibling directory with its
  own git history, viewer, and CAD pipeline. We do **not** vendor text-to-cad's
  skill scripts — instead we use `build123d` directly (see `DESIGN_DECISIONS.md`
  entry "Why we don't depend on the upstream skill scripts").
- Branch `claim2cad-mvp` initialized at the empty repo root.

### Reconnaissance findings (full notes in `docs/ARCHITECTURE_NOTES.md`)
- Read `skills/cad/SKILL.md`, `skills/cad/references/generator-contract.md`,
  `skills/cad/references/gen-step-part.md`, `skills/cad/references/gen-step-assembly.md`,
  `skills/cad/scripts/gen_step_part/cli.py`, `skills/cad/scripts/common/generation.py`
  (first 100 lines), `skills/cad/scripts/common/glb.py`, the assembly contract
  inside `generator-contract.md` lines 44–74, and a generator fixture at
  `skills/cad/scripts/common/tests/test_generation.py:120-170`.
- Read viewer code at `viewer/lib/cadDirectoryScanner.mjs:1-100`,
  `viewer/lib/render/glbMeshData.js:1-232` (the GLB → mesh-parts pipeline that
  reads `mesh.name || mesh.parent.name`), and `viewer/components/CadViewer.js:1-80`.
- Read `viewer/package.json` — Vite 7 + React 18 + three 0.160; viewer port 4178.

### Verification (Phase 1 acceptance criteria)
- `docs/ARCHITECTURE_NOTES.md` exists, 379 lines, 18+ file:line references.
- We did NOT run upstream `npm run dev` — the user explicitly asked us not to
  modify `text-to-cad/` and we have no need to. A standalone Vite viewer in
  `Claim2CAD/viewer/` is built from scratch in Phase 5.

- **Completed:** 2026-04-27 ~01:05 KST. 1 commit.

## Phase 2 — IR Schema + Golden Test Case — STARTED 2026-04-27 01:05 KST

- Wrote `claim2cad/ir_schema.py` (pydantic v2): `ClaimIR`, `Claim`,
  `Component`, `Relation`, `WhereinClause`, `SourceSpan`, discriminated
  `Dimension` union (`unspecified | relative | value`). Root-level validator
  enforces referential integrity (parent_id, relation endpoints, wherein
  targets, claim_id citations).
- Wrote `docs/IR_SCHEMA.md` walking through every field with JSON examples.
- Hand-crafted `examples/golden_robot_arm/`:
  - `claim.txt` — 9-component robot-arm claim with two `wherein` clauses and
    one dependent claim.
  - `expected_ir.json` — 9 components, 8 relations, 2 wherein clauses; spans
    are computed from the actual claim text and verified to slice to
    non-empty substrings.
  - `generator.py` — 100-line build123d script. Uses `Compound(label=..., children=...)`
    and our new `claim2cad.glb_naming.rename_glb_root_children` to round-trip
    component IDs into GLB node names. **Risk B-001 from `ARCHITECTURE_NOTES.md`
    section 6 was confirmed:** build123d's `export_gltf` *does not* preserve
    `Shape.label`s — it emits OCAF refs like `=>[0:1:1:2]`. The post-processor
    rewrites the JSON chunk in place, leaving the binary chunk untouched.
  - `claim_map.json` — 9 entries binding component_id ↔ glb_node_name (1:1
    by convention) plus label/category/kind for the viewer.

### Verification (Phase 2 acceptance criteria)
- `tests/test_ir_schema.py` — 11 tests, all pass (0.41s):
  - `test_golden_expected_ir_validates`
  - `test_golden_spans_index_into_claim_text`
  - `test_golden_independent_dependent_split`
  - `test_dimension_discriminator_round_trip`
  - `test_source_span_must_be_non_inverted`
  - `test_referential_integrity_unknown_parent_id`
  - `test_referential_integrity_unknown_relation_endpoint`
  - `test_wherein_clause_must_target_known_id`
  - `test_component_id_pattern_rejects_uppercase`
  - `test_claim_id_pattern_enforced`
  - `test_round_trip_via_model_dump_json`
- `examples/golden_robot_arm/model.step` — 131,596 B (>10 KB threshold).
- `examples/golden_robot_arm/model.glb` — 37,996 B; root scene's root node
  has 9 children named `base, fastener, first_joint, first_link, second_joint,
  second_link, end_effector, gripper, position_sensor` in insertion order.

- **Completed:** 2026-04-27 ~01:15 KST.

## Phase 3 — End-to-End Skeleton — STARTED 2026-04-27 11:00 KST

- Wrote `claim2cad/llm_client.py` — httpx-based OpenRouter wrapper with
  exponential-backoff retry on JSON-decode failure. Reads env via
  `LLMConfig.from_env`. Phase 3's tests do not exercise the network path
  (golden short-circuit + stub fallback cover both branches).
- Wrote `claim2cad/claim_parser.py` — three-tier strategy: golden short
  circuit → LLM with one validation-retry → single-component stub (logs
  WARNING). Public signature `parse_claim(text: str) -> ClaimIR`.
- Wrote `claim2cad/ir_to_cad.py` — primitive dispatch by (category, kind),
  deterministic line-along-X layout, `build_compound()` /
  `export_cad()` / `synthesize_generator()` (writes
  `pipeline_generator.py` to avoid colliding with hand-crafted
  `generator.py` in `examples/golden_robot_arm/`).
- Wrote `claim2cad/mapping.py` — flattens IR components into the richer
  `claim_map.json` schema with source_span on each row.
- Wrote `claim2cad/pipeline.py` — single CLI entry point
  (`python -m claim2cad.pipeline --claim ... --out ...`); also supports
  `--from-ir <path>` to skip the parser (used by Phase 4 tests).
- Wrote `Makefile` with `install`, `demo`, `test`, `clean` targets.
- Wrote `tests/test_pipeline.py` — 5 smoke tests in `tmp_path`:
  outputs exist, IR validates and round-trips, claim_map.components count
  matches IR, GLB root children all carry IR component IDs, STEP starts
  with `ISO-10303-21` magic.

### Verification (Phase 3 acceptance criteria)
- `make demo` runs end-to-end on the golden claim; pipeline log shows
  STEP=94,688 B, GLB=37,892 B (primitives version — Phase-5 will replace
  with type-aware shapes).
- All four outputs land in `examples/golden_robot_arm/`:
  `claim_ir.json` (8,466 B), `claim_map.json` (2,965 B), `model.step`,
  `model.glb`.
- After demo, ran the hand-crafted `examples/golden_robot_arm/generator.py`
  to restore the polished STEP/GLB so the committed example shows the
  better geometry. The Phase-3 pipeline-generated artifacts are still
  reproducible at any time via `make demo`.
- `pytest tests/` — 16 / 16 pass (3.48 s).
- LLM path was not exercised end-to-end (no API key in this run); covered
  by Phase 4 with a mocked client.

- **Completed:** 2026-04-27 ~11:12 KST. Commit `phase-3: end-to-end
  pipeline skeleton`.
