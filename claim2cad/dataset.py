"""Dataset stats + reports for ``examples/real_patents/``."""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from statistics import mean, median

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PATENTS_DIR = REPO_ROOT / "examples" / "real_patents"


def load_all() -> list[dict]:
    rows: list[dict] = []
    if not PATENTS_DIR.exists():
        return rows
    for d in sorted(PATENTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "source_metadata.json"
        claim_path = d / "claim.txt"
        if not (meta_path.exists() and claim_path.exists()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        claim = claim_path.read_text(encoding="utf-8")
        meta["_dir"] = d.name
        meta["_claim_chars"] = len(claim)
        meta["_n_figures"] = len(meta.get("saved_figures", []))
        rows.append(meta)
    return rows


def write_dataset_stats(rows: list[dict]) -> Path:
    out = PATENTS_DIR / "DATASET_STATS.md"
    if not rows:
        out.write_text("# Dataset stats\n\n(No patents collected yet.)\n", encoding="utf-8")
        return out

    classes = Counter(r["primary_class"] for r in rows)
    decades = Counter((r["publication_date"][:3] + "0s") for r in rows if r["publication_date"])
    claim_chars = [r["_claim_chars"] for r in rows]
    n_figures = [r["_n_figures"] for r in rows]

    lines: list[str] = ["# Real Patent Dataset Stats", ""]
    lines.append(f"- Total patents: **{len(rows)}**")
    lines.append(f"- Source: Google Patents (HTML, cached in `.cache/patents/`)")
    lines.append("")
    lines.append("## Distribution by USPC primary class")
    lines.append("")
    for cls, count in classes.most_common():
        lines.append(f"- **{cls}**: {count}")
    lines.append("")
    lines.append("## Publication-decade distribution")
    lines.append("")
    for dec, count in sorted(decades.items()):
        lines.append(f"- {dec}: {count}")
    lines.append("")
    lines.append("## Claim-1 length")
    lines.append("")
    lines.append(f"- min / median / mean / max: {min(claim_chars)} / {int(median(claim_chars))} / {int(mean(claim_chars))} / {max(claim_chars)} chars")
    lines.append("")
    lines.append("## Figures per patent")
    lines.append("")
    lines.append(f"- min / median / max: {min(n_figures)} / {int(median(n_figures))} / {max(n_figures)}")
    lines.append("")
    lines.append("## Patent list")
    lines.append("")
    lines.append("| ID | Title | Class | Date | Claim chars | Figs |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        title = (r.get("title") or "").replace("|", "/")[:60]
        lines.append(
            f"| `{r['patent_id']}` | {title} | {r['primary_class']} | "
            f"{r.get('publication_date','')[:10]} | {r['_claim_chars']} | {r['_n_figures']} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d rows)", out, len(rows))
    return out


def write_collection_report(rows: list[dict]) -> Path:
    out = PATENTS_DIR / "COLLECTION_REPORT.md"
    classes = Counter(r["primary_class"] for r in rows)
    lines: list[str] = ["# Phase V1-1 — Real Patent Collection Report", ""]
    lines.append(f"Collected {len(rows)} expired pre-2000 mechanical patents from "
                 "Google Patents.")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("- **Source priority** (per the brief): Google Patents → USPTO PatentsView → "
                 "WIPO PATENTSCOPE.")
    lines.append("- **Reality:** USPTO PatentsView API was retired in 2025 and now redirects "
                 "to a transition page on `data.uspto.gov` (verified by HEAD/POST request). "
                 "Pivoted to a hand-curated seed list of well-known mechanical patents "
                 "fetched directly from `patents.google.com`. This is more deterministic "
                 "than scraping Google Patents' search page (which is JS-heavy and brittle).")
    lines.append("")
    lines.append("- **Rate limit:** ≥2.2 s between fetches; cached HTML and figure binaries "
                 "in `.cache/patents/`. Re-runs are free.")
    lines.append("- **User-Agent:** `Claim2CAD-research/1.0 "
                 "(https://github.com/sungwon-chae/claim2cad)`")
    lines.append("")
    lines.append("## Distribution by class")
    lines.append("")
    for cls, count in classes.most_common():
        lines.append(f"- USPC {cls}: {count}")
    lines.append("")
    lines.append(f"## Working set: {len(rows)} patents")
    lines.append("")
    lines.append("Every patent in this directory has:")
    lines.append("")
    lines.append("- a non-empty claim 1 (100 ≤ chars ≤ 8000)")
    lines.append("- a title")
    lines.append("- ≥ 1 figure successfully downloaded")
    lines.append("- a `source_metadata.json` with the fetch URL and timestamp")
    lines.append("")
    lines.append("Pipeline-validation results land in V1-2's "
                 "`COLLECTION_VALIDATION_REPORT.md`.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote %s", out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claim2cad.dataset")
    parser.add_argument("subcommand", choices=["stats", "report", "all"], default="all", nargs="?")
    args = parser.parse_args(argv)
    logging.getLogger("claim2cad").setLevel(logging.INFO)
    rows = load_all()
    print(f"Loaded {len(rows)} patents from {PATENTS_DIR}")
    if args.subcommand in {"stats", "all"}:
        write_dataset_stats(rows)
    if args.subcommand in {"report", "all"}:
        write_collection_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
