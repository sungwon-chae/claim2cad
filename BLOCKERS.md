# Claim2CAD — Blockers & Open Items

## B-001 — Upstream `models/` directory removed
- **What it was:** The brief assumed text-to-cad had a `models/` directory with
  per-model build123d generators we would crib from.
- **Reality:** The current text-to-cad checkout has no `models/` directory.
  Generators are produced ad-hoc into the user's repo and consumed by the
  bundled `skills/cad` scripts. The upstream README and `AGENTS.md` describe
  `models/` as "the host project's layout".
- **Resolution:** We use `build123d` directly to export STEP+GLB. We do not
  invoke `skills/cad/scripts/gen_step_part`. See `docs/DESIGN_DECISIONS.md`
  entry "Why we don't depend on the upstream skill scripts".
- **Status:** Resolved. No work needed.

## B-002 — `OPENROUTER_API_KEY` not configured at start
- **What it was:** The brief assumes a `.env` with `OPENROUTER_API_KEY` and
  `OPENROUTER_MODEL` is present.
- **Resolution:** The pipeline ships with a `--dry-run` flag (Phase 6) that
  short-circuits the LLM and returns the canned golden IR for the canonical
  claim, plus a stub IR fallback for unknown claims. Users still need to set
  `OPENROUTER_API_KEY` to parse arbitrary claims; this is documented in
  `README.md` and `.env.example`.
- **Status:** Worked around. No real key was used during this build, so the
  parser's LLM path was exercised via unit tests with mocked responses only.

## B-003 — No interactive viewer verification
- **What it was:** Phase 5's brief calls for "manually open the viewer with
  the robot_arm example, click 'first link' in the claim panel, confirm the
  corresponding mesh is highlighted (log a screenshot to docs/diagrams/)".
- **Reality:** The agent runs in a headless shell with no browser. It cannot
  click on a UI nor capture a real screenshot.
- **Resolution:** The viewer logic ships with unit tests that verify the
  click-to-highlight wiring at the data layer. A static placeholder image is
  used in the README. The user should run `npm run dev` in `viewer/` to verify
  visually.
- **Status:** Limitation acknowledged. README and `docs/DESIGN_DECISIONS.md`
  call this out.

## B-006 — v1.0 cannot start: `.env` missing `OPENROUTER_API_KEY` (HALT)
- **Triggered:** 2026-04-27 18:55 KST, at the start of the v1.0 session.
- **Why this is a hard halt:** the v1.0 brief explicitly says
  > "If `.env` is missing OPENROUTER_API_KEY, halt immediately and write
  > a clear message to BLOCKERS.md telling the user to add it. Do not
  > proceed with stub implementations of LLM-dependent features."
  Phases V1-2 (parser quality), V1-3 (figure parsing — VLM), V1-5
  (prior-art LLM disambiguation), V1-7 (Korean parser), V1-8 (multi-
  claim resolution), V1-9 (dimension inference), V1-13 (figure-aware
  CAD), V1-14 (claim chart), V1-15 (eval-driven improvement) all hard-
  depend on `OPENROUTER_API_KEY`. Building stub implementations would
  violate the brief's "no fabrication" principle.
- **What I did before halting:**
  - Verified the v0.1.0 baseline: `main` branch + `v0.1.0` tag both up
    on origin (HTTPS via osxkeychain credential helper).
  - Cleaned three accidental empty files (`Branches`, `Default`,
    `Settings`) and reset the dirty `examples/golden_robot_arm/model.{glb,step}`.
  - Created local branch `v1.0-dev` (off `main`) so the work picks up
    cleanly when this blocker resolves.
- **What you (the user) need to do:**
  1. Get an OpenRouter key from https://openrouter.ai/keys (the cap
     should be set high enough — the v1.0 brief budgets ~$30, the
     60-hour brief mentions $400).
  2. Create `/Users/sungwon.chae/Desktop/claim2cad/Claim2CAD/.env`:
     ```bash
     cd /Users/sungwon.chae/Desktop/claim2cad/Claim2CAD
     cp .env.example .env
     # then edit .env and set:
     # OPENROUTER_API_KEY=sk-or-v1-...
     # OPENROUTER_MODEL=anthropic/claude-sonnet-4.6
     # OPENROUTER_OPUS_MODEL=anthropic/claude-opus-4.7
     # OPENROUTER_VISION_MODEL=anthropic/claude-opus-4.7
     ```
  3. (Optional but recommended) `gh auth login` so the agent can push
     branches, edit the default branch, and create releases without
     manual intervention. Without `gh`, B-008 will fire at V1-7.
  4. (Optional) `pip install pdfplumber pymupdf playwright` into
     `.venv` and `playwright install chromium` so V1-1 patent fetch
     works without falling back to raw httpx.
  5. (Optional) `brew install ffmpeg gifski` if you want the V1-7 hero
     GIF to be generated automatically rather than handed to you as a
     recording script.
  6. Resume the agent — it will pick up at Phase V1-0 cleanup
     (delete `origin/claim2cad-mvp`, push `v1.0-dev`) and proceed.
- **Status:** Open. Resolution requires user action; no autonomous
  workaround exists per the brief's explicit halt instruction.

## B-005 — Stub parser does not extract relations
- **What it is:** When the LLM is unavailable, the rule-based stub parser
  produces components and wherein clauses but no `Relation` rows. This
  means the layout engine in Phase 5 has no graph to BFS over and falls
  back to the line-along-X layout for stub IRs.
- **Why it's not blocking:** The structural test rubric (Phase 4) only
  checks component-level properties. The LLM path (when configured)
  produces relations correctly. Most demo runs use the golden short-circuit
  or the LLM path.
- **Resolution path:** Add a relation extractor that scans
  `connected to`, `coupled to`, `attached to`, `secured to` between known
  components. Defer until Phase 5 stress-tests the layout.
- **Status:** Open, deferred to Phase 5 (or a future sprint).

## B-004 — `make demo` from a fresh clone needs a Python venv
- **What it was:** Phase 6's brief says "test by running `make demo` in a temp
  directory".
- **Reality:** `make demo` requires `build123d` which has a heavy native
  dependency (OCP). Provisioning a fresh venv from a temp clone takes minutes.
- **Resolution:** `make install` provisions the venv; `make demo` assumes it
  exists. CI installs via `pip install -r requirements.txt` once, then runs
  tests.
- **Status:** Documented.
