"""V13-N — lightweight semantic mismatch detector.

Catches the class of failure that V13-J found by hand: an
example whose CLASSIFIER topology (or scaffold) doesn't match
what the example NAME / TITLE / FIGURE clearly imply.

Inputs we use (no LLM, no figure parsing):
  * example_id (a slug like "US5180955A_positioning_apparatus_for_arm")
  * figure_classification.json — topology, scaffold, view_type
  * batch_status.json — scaffold_id actually used, quality_tier
  * claim_map.json — component labels

Output (per example):
  {
    "has_mismatch": bool,
    "severity": "none" | "advisory" | "warning",
    "expected_topologies": [str, ...],   // from name/labels
    "actual_topology": str,
    "actual_scaffold": str,
    "reasons": [str, ...],               // human-readable
  }

The detector is deliberately conservative: a single weak signal
gets "advisory"; a strong contradiction (the example name names
a topology and the classifier picked a different family) gets
"warning". Never raises on missing files — absence of evidence
returns has_mismatch = False.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Topology family tokens we look for in the example slug or in
# claim component labels. Multiple keys can apply — the detector
# collects ALL matching ones into expected_topologies.
_FAMILY_TOKENS: list[tuple[str, list[str]]] = [
    ("positioning_apparatus",
     ["positioning_apparatus", "positioning apparatus",
      "positioning_linkage", "positioning linkage",
      "parallelogram structure", "parallelogram_structure",
      "parallel-arm", "parallelogram"]),
    ("self_closing_hinge_mechanism",
     ["self_closing_hinge", "self-closing hinge",
      "self closing hinge", "door_closer", "door closer",
      "spring_loaded_closer", "self closing mechanism"]),
    ("planetary_gear",
     ["planetary_gear", "planetary gear", "epicyclic",
      "ring gear", "sun gear", "planet pinion", "planet gear",
      "planet carrier"]),
    ("door_hinge",
     ["spring_loaded_hinge", "spring loaded hinge",
      "lift_off_hinge", "lift off hinge",
      "pintle pin", "hinge_leaf", "hinge leaf"]),
    ("two_plate_hinge",
     ["two_plate_hinge", "two plate hinge",
      "concealed hinge"]),
    ("harmonic_gear",
     ["harmonic_gear", "harmonic gear", "harmonic_drive",
      "harmonic drive", "wave generator", "flexspline"]),
    ("differential_gear",
     ["differential_gear", "differential gear",
      "spider gear"]),
    ("rotary_shaft",
     ["transmission", "drive_shaft", "drive shaft",
      "rotor_assembly", "spindle", "bearing assembly"]),
    ("robotic_arm",
     ["robotic_arm", "robotic arm", "robot_arm", "robot arm",
      "manipulator", "industrial_robot", "industrial robot"]),
    ("linkage",
     ["four_bar_linkage", "four-bar linkage",
      "linkage_assembly"]),
    ("bracket_mount",
     ["bracket_assembly", "mounting_bracket",
      "flange_mount"]),
    # Bare 'housing' is too generic — most gearbox / hinge / motor
    # patents have a housing component. Require the more specific
    # phrases.
    ("housing_panel",
     ["enclosure", "case_cover", "case cover",
      "panel_assembly", "housing assembly"]),
]


# Family compatibility — when classifier and expected disagree,
# certain pairs are still "close enough" to downgrade to advisory
# rather than warning. Symmetric closeness.
_FAMILY_NEIGHBOURS: dict[str, set[str]] = {
    "rotary_shaft": {"planetary_gear", "harmonic_gear",
                      "differential_gear"},
    "planetary_gear": {"rotary_shaft", "harmonic_gear",
                         "differential_gear"},
    "harmonic_gear": {"rotary_shaft", "planetary_gear",
                       "differential_gear"},
    "differential_gear": {"rotary_shaft", "planetary_gear",
                            "harmonic_gear"},
    "linkage": {"robotic_arm", "positioning_apparatus"},
    "robotic_arm": {"linkage", "positioning_apparatus"},
    "positioning_apparatus": {"linkage", "robotic_arm"},
    "door_hinge": {"two_plate_hinge",
                    "self_closing_hinge_mechanism"},
    "two_plate_hinge": {"door_hinge",
                          "self_closing_hinge_mechanism"},
    "self_closing_hinge_mechanism": {"door_hinge",
                                       "two_plate_hinge"},
    "bracket_mount": {"housing_panel"},
    "housing_panel": {"bracket_mount"},
}


@dataclass
class MismatchReport:
    example_id: str
    has_mismatch: bool = False
    severity: str = "none"  # "none" | "advisory" | "warning"
    expected_topologies: list[str] = field(default_factory=list)
    actual_topology: str = ""
    actual_scaffold: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(text: str) -> str:
    """Normalize a string for substring matching. Underscores
    become spaces so the example slug
    'positioning_apparatus_for_arm' matches the keyword
    'positioning apparatus'."""
    norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return " " + norm + " "


def _expected_from_id(example_id: str) -> list[str]:
    blob = _tokens(example_id)
    found = []
    for fam, kws in _FAMILY_TOKENS:
        if any(_tokens(k) in blob for k in kws) and fam not in found:
            found.append(fam)
    return found


def _expected_from_labels(claim_map: dict | None) -> list[str]:
    if not claim_map:
        return []
    blob = " ".join(_tokens(r.get("label", ""))
                     for r in claim_map.get("components", []))
    found = []
    for fam, kws in _FAMILY_TOKENS:
        if any(_tokens(k) in blob for k in kws) and fam not in found:
            found.append(fam)
    return found


def detect_one(example_dir: Path) -> MismatchReport:
    rep = MismatchReport(example_id=example_dir.name)

    cls_path = example_dir / "figure_classification.json"
    bs_path = example_dir / "batch_status.json"
    cm_path = example_dir / "claim_map.json"

    cls = json.loads(cls_path.read_text("utf-8")) if cls_path.exists() else {}
    bs = json.loads(bs_path.read_text("utf-8")) if bs_path.exists() else {}
    cm = json.loads(cm_path.read_text("utf-8")) if cm_path.exists() else None

    rep.actual_topology = cls.get("topology", "") or ""
    rep.actual_scaffold = bs.get("scaffold_id", "") or cls.get(
        "recommended_scaffold", "") or ""

    expected_id = _expected_from_id(example_dir.name)
    expected_lbl = _expected_from_labels(cm)
    expected = list(dict.fromkeys(expected_id + expected_lbl))
    rep.expected_topologies = expected

    if not expected:
        return rep  # no signal — leave has_mismatch = False

    if rep.actual_topology in expected:
        return rep  # classifier agrees with at least one signal

    # Strong signal: the example slug names a topology that the
    # classifier didn't pick. That's a warning unless the actual
    # topology is a near-neighbour family.
    in_id_strong = any(t in expected_id for t in expected_id)
    near = (rep.actual_topology in
             _FAMILY_NEIGHBOURS.get(expected[0], set()))
    if in_id_strong and not near:
        rep.has_mismatch = True
        rep.severity = "warning"
        rep.reasons.append(
            f"example name implies {expected[0]!r}, "
            f"classifier picked {rep.actual_topology!r}"
        )
    elif near:
        rep.has_mismatch = True
        rep.severity = "advisory"
        rep.reasons.append(
            f"classifier picked {rep.actual_topology!r}; "
            f"expected near-family {expected[0]!r}"
        )
    else:
        rep.has_mismatch = True
        rep.severity = "advisory"
        rep.reasons.append(
            f"claim labels suggest {expected!r}; "
            f"classifier picked {rep.actual_topology!r}"
        )

    # Extra check: scaffold_id and topology disagree.
    if (rep.actual_topology and rep.actual_scaffold
            and rep.actual_topology != rep.actual_scaffold
            and rep.actual_scaffold not in (
                "fallback_grid", "generic_exploded")):
        # Only emit when scaffold is not the canonical mapping.
        # The classifier already maps planetary_gear → planetary_gear
        # post-V13-K, but older runs may still show
        # planetary_gear → rotary_shaft. Surface it.
        rep.reasons.append(
            f"scaffold {rep.actual_scaffold!r} does not match "
            f"topology {rep.actual_topology!r}"
        )
        if rep.severity == "none":
            rep.has_mismatch = True
            rep.severity = "advisory"

    return rep


def detect_all(real_patents_dir: Path) -> list[MismatchReport]:
    out = []
    for ex in sorted(real_patents_dir.iterdir()):
        if not ex.is_dir():
            continue
        out.append(detect_one(ex))
    return out


def write_report(reports: list[MismatchReport],
                  out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "SEMANTIC_MISMATCH_REPORT.json"
    m = out_dir / "SEMANTIC_MISMATCH_REPORT.md"
    j.write_text(json.dumps({
        "n_examples": len(reports),
        "n_with_mismatch": sum(1 for r in reports if r.has_mismatch),
        "examples": [r.to_dict() for r in reports],
    }, indent=2) + "\n", encoding="utf-8")
    md = ["# V1.3 semantic mismatch report\n"]
    n_warn = sum(1 for r in reports if r.severity == "warning")
    n_adv = sum(1 for r in reports if r.severity == "advisory")
    md.append(f"{n_warn} warning, {n_adv} advisory, "
               f"{len(reports) - n_warn - n_adv} clean.\n")
    md.append("| ID | severity | actual topology | expected | reason |")
    md.append("|---|---|---|---|---|")
    for r in reports:
        if not r.has_mismatch:
            continue
        reason = (r.reasons[0] if r.reasons else "").replace("|", "/")
        md.append(
            f"| `{r.example_id}` | **{r.severity}** | "
            f"{r.actual_topology} | "
            f"{', '.join(r.expected_topologies)} | "
            f"{reason} |"
        )
    md.append("")
    m.write_text("\n".join(md), encoding="utf-8")
    return j, m


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--real-patents-dir", type=Path,
                    default=Path("examples/real_patents"))
    p.add_argument("--report-dir", type=Path,
                    default=Path("examples/reports"))
    args = p.parse_args(argv)
    reps = detect_all(args.real_patents_dir)
    j, m = write_report(reps, args.report_dir)
    print(f"\nWrote {j}\nWrote {m}")
    n = sum(1 for r in reps if r.has_mismatch)
    print(f"{n}/{len(reps)} examples have a semantic mismatch")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
