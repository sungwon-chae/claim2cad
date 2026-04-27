# Changelog

All notable changes documented here. This project follows semantic versioning.

## [Unreleased] — v1.0-dev

### Added (V1-9)
- Deterministic dimension extractor (`claim2cad/dimension_extractor.py`)
  for English and Korean.
  - Patterns: explicit values (``"30 mm"``), approximate
    (``"approximately 30 mm"`` / ``"약 30 mm"``), ranges
    (``"between 10 and 20 mm"`` / ``"5 내지 10 mm"``), at-least /
    at-most (``"at least 5 mm"`` / ``"5 mm 이상"``), comparatives
    (``"longer than the first link"`` / ``"제1 링크보다 긴"``).
  - Unit normalisation across mm / cm / m / in / ft / deg + Korean
    aliases.
- Stub parser populates dimensions automatically from element text;
  qualifier (approximate / minimum / range:lo-hi) is recorded in
  `Component.constraints` (no precision loss).
- LLM parser gets a `_backfill_dimensions` post-pass that fills
  `unspecified` entries from source-span text — LLM-set dimensions
  pass through unchanged.
- Korean head-noun extraction now follows trailing possessive ``의``,
  so ``"길이 50 mm 의 제1 링크"`` resolves to head "제1 링크".
- 26 new tests in `tests/test_dimensions.py`. Total: 87 passed.

### Added (V1-8)
- Multi-claim hierarchy operations.
  - `claim2cad/claim_hierarchy.py`: `claim_chain`, `components_for_claim`,
    `filter_ir_to_claim`, `hierarchy_summary`.
  - Pipeline `--filter-claim N` flag — emit a single-claim CAD view
    (claim N + ancestors). The filtered IR re-validates via the existing
    referential-integrity check; relations with orphan endpoints and
    wherein-clause targets that fell out of the kept set are pruned.
  - Pipeline always writes `claim_hierarchy.json` next to the IR
    (`--no-hierarchy` to skip).
- Manifest fields: `n_claims`, `n_dependent_claims`, `max_claim_depth`,
  `claim_hierarchy_path`. Examples with depth ≥ 2 get a `multi_claim` tag.
- New `examples/multi_claim_drone/` — quadrotor with 5 claims and
  hierarchy depth 4 (claim_5 → claim_4 → claim_3 → claim_1, sibling
  claim_2). Exercises sibling-branch isolation in the filter.
- All 30 examples ship `claim_hierarchy.json`.
- 17 new tests in `tests/test_multi_claim.py`. Total: 61 passed.

### Added (V1-7)
- Korean (KIPO/KIPRIS) patent-claim support.
  - `claim2cad/lang.py`: Hangul-block language detector.
  - `claim2cad/lang_ko.py`: claim-split / dependent / preamble-tail /
    element-split / NP-terminator / relative-clause-verb regexes,
    Hangul→English head-noun translations (~40 entries), ordinal map
    (제1→first…), Korean kind heuristics, embedded-joint hints
    (`회전 가능하게 결합` → revolute_joint).
  - Segmenter and parser dispatched on `detect_language(text)`. The
    Korean parser scans for the *last* relative-clause verb to find the
    head noun (Korean is head-final), romanises Korean tokens before
    slugifying, and reuses the English kind heuristics on the
    romanised label as a second pass.
- New `examples/korean_robot_arm/` with bilingual claim + manifest
  staging (tag `korean`, source `korean`).
- 15 new tests in `tests/test_korean.py`. Test totals: 44 passed.

### Added
- LLM model routing (`claim2cad.llm_client.route`) with `HEAVY_TASKS` /
  `ROUTINE_TASKS` taxonomy. Heavy reasoning → Opus 4.7, routine →
  Sonnet 4.6. Vision tasks → Opus 4.7.
- Cost tracker (`claim2cad.cost_tracker`) writing JSON-lines to
  `logs/cost_tracker.json`; auto-downgrade to Sonnet when cumulative
  cost exceeds soft cap (`CLAIM2CAD_COST_SOFT_CAP`, default $60).
- `.env` autoload via python-dotenv at package import.
- `BACKLOG.md` seeded with high-/medium-/low-value follow-ups.

### Changed
- CI matrix branches: `claim2cad-mvp` → `v1.0-dev`.
- Default model bumped from `anthropic/claude-3.5-sonnet` →
  `anthropic/claude-sonnet-4.6`.

### Fixed
- `llm_client._extract_json` now strips markdown code fences before
  parsing — some OpenRouter providers wrap responses in
  `\`\`\`json … \`\`\`` despite `response_format: json_object`.
  Without this fix, the parser hits its retry budget on every real
  patent and falls back to the rule-based stub.

### Added (V1-1, V1-2)
- `claim2cad.patent_collector` — Google Patents direct fetch with
  HTTP caching and per-patent `source_metadata.json`. Hand-curated
  seed list of 33 expired pre-2000 mechanical patents (USPC 074, 901,
  414, 16).
- `claim2cad.dataset` — dataset stats + collection report writer.
- `claim2cad.validator` — batch pipeline runner, per-patent
  `result.json`, structural quality grade
  (`good | partial | fail`), markdown rollup.
- `claim2cad.known_failure_patterns` — catalogue of observed
  failure modes (e.g. P001 markdown-fenced JSON).
- 25 real patents under `examples/real_patents/`, each with
  `claim.txt`, `figures/figure_*.png`, `source_metadata.json`,
  `claim_ir.json`, `claim_map.json`, `model.step`, `model.glb`,
  `pipeline_generator.py`, `result.json`.
- V1-2 baseline: **25/25 patents graded "good"** at iteration 0
  on the structural eval. No iterative improvement needed.

### Added (V1-6)
- `claim2cad.urdf_export` — IR → URDF XML emitter. Builds a
  kinematic tree from the IR relation graph, emits `<link>` /
  `<joint>` with sensible primitives + default limits, and writes
  `model.urdf` next to the IR.
- 28 URDFs generated (every example). Two have movable joints:
  `golden_robot_arm` (2 revolute) and `US4575297A_puma_industrial_robot`
  (6 revolute).
- Manifest gains `urdf_path` + `movable_joints[]` + a `kinematic`
  tag. URDFs staged into the viewer.
- Viewer:
  - `viewer/src/urdf.ts` — DOMParser-based URDF reader.
  - `KinematicSliders.tsx` — slider panel with degrees/mm display
    and a reset button.
  - `Scene.tsx` applies joint values to GLB nodes — rotation about
    the joint origin for revolute/continuous, translation along the
    joint axis for prismatic.
  - `App.tsx` adds a "Joints (N)" button that toggles the slider
    panel (only when the loaded example has movable joints).

### Added (V1-5)
- `claim2cad.prior_art` — bipartite-greedy fuzzy matcher + Sonnet 4.6
  disambiguation. CLI:
  `python -m claim2cad.prior_art --base <dir> --compare <dir>` writes
  `<base>/diff_<comp_id>.json` with `matched`, `novel_in_base`,
  `only_in_comparison` rows.
- 4 demo diffs precomputed: `golden_robot_arm` × {Unimate 1962, PUMA
  1982}; `planetary_gear` × {US3705522A 1971, US3789698A 1972}.
- Manifest gains `diffs_available[]`. Diff JSONs are staged into
  `viewer/public/data/<base>/`.
- New viewer component `PriorArtOverlay.tsx` (sectioned matched /
  novel / prior-only list with click-to-select rows).
- `Scene.tsx` accepts an optional `diff` prop — when set, mesh tints
  switch to diff status colours (matched white, novel green,
  unmatched dimmed).
- `App.tsx` header gains a "Compare to prior art…" `<select>` that
  swaps the right pane from `FigurePanel` to `PriorArtOverlay` and
  re-tints the scene.
- Total V1-5 cost: $0.06 across 4 LLM disambiguation calls (Opus 4.7).

### Added (V1-4)
- **3-pane viewer**: left = ClaimPanel (existing), centre = 3D scene
  (existing), right = new `FigurePanel.tsx`. Layout collapses to
  2-pane when no figure is available.
- `FigurePanel` renders the patent figure as `<img>` with absolutely
  positioned hotspots over each VLM-extracted bbox. Hotspots highlight
  in sync with the claim panel and 3D scene via lifted state in
  `App.tsx`.
- Manifest schema bumped to `0.2.0`. Each example entry now carries
  `figure_map_path`, `figure_image_path`, `figure_coverage`,
  `source` (`synthetic` / `real_patent` / `korean`), and `tags`.
- `claim2cad.manifest` now discovers real-patent directories under
  `examples/real_patents/` and stages their figure images +
  `figure_map.json` into `viewer/public/data/<base>/`.
- Header dropdown groups synthetic vs. real patents and shows a
  coverage badge (★ ◐ ◷ ○) before each real-patent title. New
  "full-mapping only" filter button surfaces the 8 fully-mapped
  patents quickly.

### Added (V1-3)
- `claim2cad.llm_vision` — OpenRouter vision wrapper with cost
  recording and JSON-mode parsing.
- `claim2cad.figure_parser` — three-pass component → figure-number
  matcher (regex / rule / LLM-rematch), `process_patent_directory`,
  `process_all` batch driver with caching.
- `Component.figure_number` and `Component.figure_references` fields
  added to the IR schema (both optional, backward-compatible).
- `examples/real_patents/<id>/figure_map.json` for all 25 patents.
- IRs and `claim_map.json` files updated in-place with figure-number
  stamps.
- V1-3 results: **25/25** figure_maps written, **8/25** with full
  mapping (brief target ≥ 5), VLM cost **$1.56** (brief target < $5).

## [v0.1.0] — 2026-04-27
- Initial release. Hand-crafted examples (robot arm, hinge, planetary gear).
- Two-pane viewer with bidirectional highlighting.
- Hybrid LLM + rule-based claim parser.
- pydantic v2 IR with referential integrity validation.
- build123d → STEP/GLB pipeline with GLB node-name post-processor.
- pytest suite (29 tests) and GitHub Actions CI (Python + viewer jobs).
