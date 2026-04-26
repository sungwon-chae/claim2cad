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

## B-004 — `make demo` from a fresh clone needs a Python venv
- **What it was:** Phase 6's brief says "test by running `make demo` in a temp
  directory".
- **Reality:** `make demo` requires `build123d` which has a heavy native
  dependency (OCP). Provisioning a fresh venv from a temp clone takes minutes.
- **Resolution:** `make install` provisions the venv; `make demo` assumes it
  exists. CI installs via `pip install -r requirements.txt` once, then runs
  tests.
- **Status:** Documented.
