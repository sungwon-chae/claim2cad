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

## [v0.1.0] — 2026-04-27
- Initial release. Hand-crafted examples (robot arm, hinge, planetary gear).
- Two-pane viewer with bidirectional highlighting.
- Hybrid LLM + rule-based claim parser.
- pydantic v2 IR with referential integrity validation.
- build123d → STEP/GLB pipeline with GLB node-name post-processor.
- pytest suite (29 tests) and GitHub Actions CI (Python + viewer jobs).
