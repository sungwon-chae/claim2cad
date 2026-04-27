# Changelog

All notable changes documented here. This project follows semantic versioning.

## [Unreleased] — v1.0-dev

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
