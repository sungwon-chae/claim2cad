# Claim2CAD — Backlog

A living list of follow-ups. The maintenance loop pulls from here.

## High value
- Multi-figure understanding (combine info from figure 1 + figure 2 to refine geometry)
- Figure-to-3D directly: extract geometry primitives from figures, not just labels
- WIPO/EPO patent support (currently US-biased)
- Patent-to-FreeCAD-script (open source CAD ecosystem integration)
- Browser extension: highlight a patent on Google Patents → instant Claim2CAD view

## Medium value
- Claim chart export: formal limitation × accused-product table (PDF)
- Citation graph: which patents cite this one, do they overlap in components?
- Component library: pre-built recognized parts (off-the-shelf bearings, motors)
- Batch eval reports as HTML dashboards
- VS Code extension for patent attorneys

## Low / quality-of-life
- Bundle size <500KB (currently ~1MB)
- Mobile-responsive viewer
- Dark mode (currently dark-only — needs light variant)
- Keyboard shortcuts in viewer
- Localization framework (en, ko, ja, zh, de, fr)

## Research
- Fine-tune small model on patent claim → IR (avoid OpenRouter cost long-term)
- Prior art search: given a claim, find related patents automatically
- Claim drafting assistant: given an invention description, draft claim 1 + figures

---

## Notes for maintenance loop
- Pull from this list when no BLOCKER, eval failure, or TODO is pressing.
- After completing an item, move it to CHANGELOG and delete from here.
- Add new items the moment they're observed (don't trust memory).
