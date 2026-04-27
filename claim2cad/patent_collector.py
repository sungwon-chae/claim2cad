"""Real-patent collection — Google Patents direct fetch.

Strategy (after USPTO PatentsView retired):

1. **Curated seed list** of ~35 well-known expired pre-2000 mechanical
   patents covering robot arms (USPC 901 / 414), gear assemblies (074),
   and hinges (16). Hand-picked rather than discovered to avoid fragile
   scraping of search results.
2. **Fetch** each patent's HTML from ``patents.google.com``. Extract:
   - title
   - claim 1 text
   - first ~3 figure image URLs (patentimages.storage.googleapis.com)
   - publication date
3. **Cache** raw HTML + images in ``.cache/patents/<id>/``. Re-runs are
   free.
4. **Save** working candidates to
   ``examples/real_patents/US_<id>_<slug>/`` with:
   - ``claim.txt`` (claim 1, dedented)
   - ``figures/figure_<n>.png``
   - ``source_metadata.json``

Rate limit: ≥2 s between fetches. User-Agent identifies the project.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "patents"
EXAMPLES_DIR = REPO_ROOT / "examples" / "real_patents"

USER_AGENT = (
    "Claim2CAD-research/1.0 (https://github.com/sungwon-chae/claim2cad)"
)
RATE_LIMIT_SECONDS = 2.2


# ---------------------------------------------------------------------------
# Curated seed list
# ---------------------------------------------------------------------------
# Each entry: (USPTO patent number with kind code, short slug, primary class).
# Hand-picked from well-known mechanical patent histories. Pre-2000 priority
# dates so they're public domain. All have at least one figure with numbered
# components.

SEED_PATENTS: list[tuple[str, str, str]] = [
    # Robot manipulators (USPC 901 / 414)
    ("US3279624A", "unimate_industrial_robot", "901"),
    ("US4329110A", "manipulator_with_remote_control", "414"),
    ("US4392776A", "robotic_hand_with_compliance", "901"),
    ("US4407625A", "multi_arm_robotic_assembly", "901"),
    ("US4486142A", "kuka_articulated_arm", "901"),
    ("US4575297A", "puma_industrial_robot", "901"),
    ("US4655675A", "robotic_assembly_apparatus", "414"),
    ("US4762016A", "robotic_drive_unit", "901"),
    ("US4816730A", "autonomous_mobile_robot", "901"),
    ("US4955250A", "multiple_forearm_robot", "414"),
    ("US5180955A", "positioning_apparatus_for_arm", "901"),
    ("US5239246A", "force_reflecting_manipulator", "901"),
    # Gear assemblies (USPC 074)
    ("US3705522A", "planetary_gear_with_idler", "074"),
    ("US3789698A", "compact_planetary_drive", "074"),
    ("US3897696A", "harmonic_gear_drive", "074"),
    ("US4106366A", "automotive_planetary_gearbox", "074"),
    ("US4196635A", "spur_gear_differential", "074"),
    ("US4391163A", "planetary_speed_reducer", "074"),
    ("US4467670A", "epicyclic_transmission", "074"),
    ("US4729261A", "compact_gear_reduction", "074"),
    ("US4856377A", "planetary_drive_apparatus", "074"),
    ("US5042321A", "two_stage_planetary_gear", "074"),
    # Hinges / pivots (USPC 16)
    ("US4470181A", "self_closing_hinge", "16"),
    ("US4502185A", "concealed_hinge_assembly", "16"),
    ("US4807331A", "spring_loaded_hinge", "16"),
    ("US5107569A", "multi_axis_pivot_hinge", "16"),
    ("US5295277A", "lid_hinge_assembly", "16"),
    ("US5564163A", "adjustable_door_hinge", "16"),
    ("US5701636A", "concealed_pivot_hinge", "16"),
    # Mixed / bonus
    ("US4365928A", "fastener_securing_apparatus", "411"),
    ("US4500238A", "multi_segment_arm_apparatus", "414"),
    ("US4828453A", "modular_assembly_robot", "901"),
    ("US5083070A", "joint_for_multi_link_arm", "901"),
    ("US5267483A", "harmonic_drive_arm", "074"),
]


@dataclass
class FetchedPatent:
    patent_id: str
    slug: str
    primary_class: str
    title: str
    claim_text: str
    figure_urls: list[str]
    publication_date: str
    fetch_url: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# HTTP layer with cache
# ---------------------------------------------------------------------------


def _cache_path(patent_id: str) -> Path:
    return CACHE_DIR / patent_id


def _cached_html(patent_id: str) -> str | None:
    p = _cache_path(patent_id) / "page.html"
    if p.exists() and p.stat().st_size > 1000:
        return p.read_text(encoding="utf-8")
    return None


def _save_html(patent_id: str, html: str) -> None:
    cache = _cache_path(patent_id)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "page.html").write_text(html, encoding="utf-8")


_LAST_FETCH_TS = 0.0


def _rate_limit() -> None:
    global _LAST_FETCH_TS
    elapsed = time.time() - _LAST_FETCH_TS
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _LAST_FETCH_TS = time.time()


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def fetch_html(patent_id: str, *, force: bool = False) -> str:
    if not force:
        cached = _cached_html(patent_id)
        if cached is not None:
            logger.debug("Cache hit: %s", patent_id)
            return cached
    _rate_limit()
    url = f"https://patents.google.com/patent/{patent_id}/en"
    logger.info("Fetching %s", url)
    with _http_client() as client:
        r = client.get(url)
    r.raise_for_status()
    html = r.text
    _save_html(patent_id, html)
    return html


def _ext_from_response(url: str, response: httpx.Response) -> str:
    """Pick a file extension from the response's Content-Type, falling
    back to the URL suffix and then to ``png``."""
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if "png" in ctype:
        return "png"
    if "jpeg" in ctype or "jpg" in ctype:
        return "jpg"
    if "tiff" in ctype:
        return "tif"
    if "gif" in ctype:
        return "gif"
    suffix = url.rsplit(".", 1)[-1].split("?")[0].lower()
    if suffix in {"png", "jpg", "jpeg", "tif", "tiff", "gif"}:
        return "jpg" if suffix == "jpeg" else suffix
    return "png"


def fetch_image(url: str, dest_dir: Path, base_name: str) -> Path | None:
    """Download ``url`` to ``dest_dir/<base_name>.<ext>`` and return the
    final path, or None on failure."""
    # If a previously downloaded file exists with any known extension,
    # short-circuit (cache).
    for ext in ("png", "jpg", "tif", "gif"):
        existing = dest_dir / f"{base_name}.{ext}"
        if existing.exists() and existing.stat().st_size > 1024:
            return existing
    _rate_limit()
    try:
        with _http_client() as client:
            r = client.get(url)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch image %s: %s", url, exc)
        return None
    ext = _ext_from_response(url, r)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{base_name}.{ext}"
    dest_path.write_bytes(r.content)
    if dest_path.stat().st_size <= 1024:
        return None
    return dest_path


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _extract_title(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "DC.title"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    h1 = soup.find("h1", attrs={"id": "title"})
    return h1.get_text(strip=True) if h1 else ""


def _extract_publication_date(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "DC.date"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    return ""


def _extract_claim_1(soup: BeautifulSoup) -> str:
    """Return the text of claim 1 (or the first independent claim)."""
    # Google Patents wraps claims in <claim id="CLM-00001"> or div.claim.
    for tag in soup.select("claim, div.claim, claim-text"):
        # First top-level claim.
        text = tag.get_text(" ", strip=True)
        if text and re.match(r"^\s*1\.", text):
            return _normalize_claim(text)
    # Fall back: search for "1." prefix in any claims section.
    section = soup.find("section", attrs={"itemprop": "claims"})
    if section:
        text = section.get_text(" ", strip=True)
        match = re.search(r"\b1\.\s.+?(?=\n?\s*\b2\.\s|\Z)", text, flags=re.DOTALL)
        if match:
            return _normalize_claim(match.group(0))
    return ""


def _normalize_claim(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Strip duplicate leading "1. 1." artifacts produced by some Google Patents
    # layouts.
    text = re.sub(r"^(1\.\s+){2,}", "1. ", text)
    return text


def _extract_figure_urls(soup: BeautifulSoup, max_figures: int = 3) -> list[str]:
    seen: list[str] = []
    for meta in soup.find_all("meta", attrs={"itemprop": "full"}):
        u = meta.get("content")
        if u and u.startswith("http") and u not in seen:
            seen.append(u)
    if not seen:
        for img in soup.select("img.style-scope.patent-image, figure img"):
            u = img.get("src") or img.get("data-src")
            if u and u.startswith("http") and u not in seen:
                seen.append(u)
    return seen[:max_figures]


def parse_patent_html(patent_id: str, html: str, *, primary_class: str = "?", slug: str = "?") -> FetchedPatent:
    soup = BeautifulSoup(html, "lxml")
    return FetchedPatent(
        patent_id=patent_id,
        slug=slug,
        primary_class=primary_class,
        title=_extract_title(soup),
        claim_text=_extract_claim_1(soup),
        figure_urls=_extract_figure_urls(soup),
        publication_date=_extract_publication_date(soup),
        fetch_url=f"https://patents.google.com/patent/{patent_id}/en",
        fetched_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def _example_dirname(patent: FetchedPatent) -> str:
    return f"{patent.patent_id}_{patent.slug}"


def save_patent(patent: FetchedPatent, *, fetch_figures: bool = True) -> Path:
    dest = EXAMPLES_DIR / _example_dirname(patent)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "claim.txt").write_text(patent.claim_text + "\n", encoding="utf-8")
    figures_dir = dest / "figures"
    saved_figures: list[str] = []
    if fetch_figures:
        for i, url in enumerate(patent.figure_urls, 1):
            saved = fetch_image(url, figures_dir, f"figure_{i}")
            if saved:
                saved_figures.append(saved.name)
    metadata = patent.to_dict()
    metadata["saved_figures"] = saved_figures
    (dest / "source_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return dest


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def is_acceptable(patent: FetchedPatent) -> tuple[bool, str]:
    if not patent.claim_text:
        return False, "empty_claim"
    if len(patent.claim_text) < 100:
        return False, "claim_too_short"
    # Real US patent claims commonly run 1000-6000 chars. We cap at 8000 to
    # exclude the absolute longest mega-claims that would blow the LLM
    # context budget without giving up on typical industrial cases.
    if len(patent.claim_text) > 8000:
        return False, "claim_too_long"
    if not patent.title:
        return False, "no_title"
    if not patent.figure_urls:
        return False, "no_figures"
    return True, "ok"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_collection(seed: Iterable[tuple[str, str, str]] = SEED_PATENTS) -> dict:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    accepted: list[FetchedPatent] = []
    rejected: list[tuple[str, str]] = []
    fetch_failures: list[tuple[str, str]] = []
    seen: set[str] = set()
    for patent_id, slug, primary_class in seed:
        if patent_id in seen:
            continue
        seen.add(patent_id)
        try:
            html = fetch_html(patent_id)
        except httpx.HTTPError as exc:
            logger.warning("Fetch failed %s: %s", patent_id, exc)
            fetch_failures.append((patent_id, str(exc)))
            continue
        patent = parse_patent_html(html=html, patent_id=patent_id, slug=slug, primary_class=primary_class)
        ok, reason = is_acceptable(patent)
        if not ok:
            rejected.append((patent_id, reason))
            logger.info("Rejected %s: %s", patent_id, reason)
            continue
        save_patent(patent)
        accepted.append(patent)
        logger.info(
            "Accepted %s (%d chars, %d figures): %s",
            patent_id,
            len(patent.claim_text),
            len(patent.figure_urls),
            patent.title[:60],
        )
        if len(accepted) >= 25:
            break
    return {
        "accepted": [p.to_dict() for p in accepted],
        "rejected": rejected,
        "fetch_failures": fetch_failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claim2cad.patent_collector")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    logging.getLogger("claim2cad").setLevel(logging.INFO)
    result = run_collection()
    accepted = result["accepted"][: args.limit]
    if args.report:
        print(json.dumps({
            "accepted_count": len(accepted),
            "rejected_count": len(result["rejected"]),
            "fetch_failure_count": len(result["fetch_failures"]),
            "rejected_breakdown": result["rejected"],
            "fetch_failures": result["fetch_failures"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
