#!/usr/bin/env python3
"""
fetch_openalex.py — Deterministic ingestion for the 2D mesoscopic physics tracker.

Pure standard library. No pip. Idempotent — skips already-tracked arXiv IDs.

TWO MODES:
  TARGET_IDS (non-empty) — fetches specific papers by arXiv ID. Use for testing
                            and manual backfill. Ignores date range.
  TARGET_IDS = []         — weekly mode: fetches cond-mat.mes-hall papers from
                            the past LOOKBACK_DAYS days via OpenAlex.

Primary source: OpenAlex API (no arXiv API dependency).
PDF: downloaded from open-access URL returned by OpenAlex.
Corresponding authors: extracted from PDF first page via pdftotext.
No Tier 2 validation — OpenAlex is a structured database, not generated text.
"""

import datetime
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
TARGET_IDS    = ["2504.06972"]

CATEGORY      = "cond-mat.mes-hall"
LOOKBACK_DAYS = 8
MAX_RESULTS   = 200

BASE_DIR      = Path(__file__).parent
METADATA_DIR  = BASE_DIR / "metadata"
PAPERS_DIR    = BASE_DIR / "papers"
PAPERS_JSON   = METADATA_DIR / "papers.json"

OPENALEX_API  = "https://api.openalex.org/works"
ARXIV_ABS     = "https://arxiv.org/abs"
USER_AGENT    = "2DMesoscopicTracker/1.0 (research; contact via GitHub)"

SELECT_FIELDS = ",".join([
    "id", "title", "abstract_inverted_index", "publication_date",
    "authorships", "ids", "doi", "open_access", "locations",
    "primary_location", "topics",
])


# ── Directory helpers ──────────────────────────────────────────────────────────
def ensure_dirs():
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)


def load_papers():
    if PAPERS_JSON.exists():
        with open(PAPERS_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def save_papers(papers):
    with open(PAPERS_JSON, "w", encoding="utf-8") as fh:
        json.dump(papers, fh, indent=2, ensure_ascii=False)


def existing_ids(papers):
    return {p["arxiv_id"] for p in papers}


# ── HTTP helper ────────────────────────────────────────────────────────────────
def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.status
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except Exception as exc:
        return None, 0


# ── OpenAlex: fetch by specific IDs ───────────────────────────────────────────
def query_openalex_by_ids(ids):
    """Fetch specific papers by arXiv ID list using landing_page_url filter."""
    results = []
    for arxiv_id in ids:
        arxiv_url = f"{ARXIV_ABS}/{arxiv_id}"
        params = urllib.parse.urlencode({
            "filter": f"locations.landing_page_url:{arxiv_url}",
            "select": SELECT_FIELDS,
            "per_page": 1,
        })
        url = f"{OPENALEX_API}?{params}"
        body, status = fetch(url, timeout=20)
        if status != 200 or not body:
            print(f"  [OpenAlex] HTTP {status} for {arxiv_id} — FAILED")
            continue
        data = json.loads(body)
        hits = data.get("results", [])
        if not hits:
            print(f"  [OpenAlex] No record found for {arxiv_id} — FAILED")
            continue
        results.append((arxiv_id, hits[0]))
        time.sleep(0.5)
    print(f"  [OpenAlex] {len(results)}/{len(ids)} papers found")
    return results


# ── OpenAlex: fetch by date range ─────────────────────────────────────────────
def query_openalex_weekly(start_date, end_date):
    """Fetch cond-mat.mes-hall papers submitted in [start_date, end_date]."""
    # OpenAlex source ID for arXiv cond-mat.mes-hall
    # Filter: primary_location is arXiv + topic matches mesoscopic/cond-mat
    params = urllib.parse.urlencode({
        "filter": (
            f"primary_location.source.id:S4306400194,"
            f"publication_date:{start_date.isoformat()}:{end_date.isoformat()}"
        ),
        "select": SELECT_FIELDS,
        "per_page": MAX_RESULTS,
        "sort": "publication_date:desc",
    })
    url = f"{OPENALEX_API}?{params}"
    body, status = fetch(url, timeout=45)
    if status != 200 or not body:
        print(f"  [OpenAlex] HTTP {status} — FAILED")
        return []
    data = json.loads(body)
    results = data.get("results", [])
    print(f"  [OpenAlex] {len(results)} papers returned")
    # Extract arXiv ID from each result
    out = []
    for work in results:
        arxiv_id = _extract_arxiv_id(work)
        if arxiv_id:
            out.append((arxiv_id, work))
    return out


# ── OpenAlex parsers ───────────────────────────────────────────────────────────
def _extract_arxiv_id(work):
    """Extract arXiv ID from OpenAlex work locations."""
    for loc in work.get("locations", []):
        url = loc.get("landing_page_url") or ""
        if "/abs/" in url and "arxiv" in url.lower():
            return url.split("/abs/")[-1].strip()
    pl = work.get("primary_location") or {}
    url = pl.get("landing_page_url") or ""
    if "/abs/" in url:
        return url.split("/abs/")[-1].strip()
    return None


def _reconstruct_abstract(inverted_index):
    """OpenAlex stores abstracts as {word: [positions]}. Reconstruct word order."""
    if not inverted_index:
        return ""
    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _parse_authors(authorships):
    """Extract deduplicated author list preserving order."""
    seen = set()
    authors = []
    for a in authorships:
        name = (a.get("author") or {}).get("display_name")
        if name and name not in seen:
            seen.add(name)
            authors.append(name)
    return authors


def _parse_affiliations(authorships):
    """Extract institutions from first author."""
    if not authorships:
        return []
    return [
        inst["display_name"]
        for inst in authorships[0].get("institutions", [])
        if inst.get("display_name")
    ]


def parse_work(arxiv_id, work):
    """Convert OpenAlex work object to our internal record format."""
    authorships = work.get("authorships", [])
    authors     = _parse_authors(authorships)
    raw_doi     = work.get("doi") or ""
    doi         = raw_doi.replace("https://doi.org/", "").strip() or None

    # Open-access PDF URL
    oa      = work.get("open_access", {})
    pdf_url = oa.get("oa_url") or None
    if not pdf_url:
        for loc in work.get("locations", []):
            if loc.get("pdf_url") and "arxiv" in (loc.get("pdf_url") or "").lower():
                pdf_url = loc["pdf_url"]
                break

    return {
        "arxiv_id":           arxiv_id,
        "openalex_id":        work.get("id"),
        "title":              work.get("title") or "",
        "abstract":           _reconstruct_abstract(work.get("abstract_inverted_index")),
        "authors":            authors,
        "first_author":       authors[0] if authors else "",
        "arxiv_affiliations": _parse_affiliations(authorships),
        "published":          work.get("publication_date") or "",
        "categories":         ["cond-mat.mes-hall"],
        "doi":                doi,
        "url":                f"{ARXIV_ABS}/{arxiv_id}",
        "_pdf_url":           pdf_url,
    }


# ── PDF download ───────────────────────────────────────────────────────────────
def download_pdf(arxiv_id, pdf_url):
    """Download open-access PDF. Returns relative path string or None."""
    if not pdf_url:
        return None
    safe_id  = arxiv_id.replace("/", "_")
    filename = f"{safe_id}.pdf"
    dest     = PAPERS_DIR / filename

    if dest.exists():
        print(f"  pdf: already exists — papers/{filename}")
        return f"papers/{filename}"

    body, status = fetch(pdf_url, timeout=90)
    if status != 200 or not body:
        print(f"  pdf: HTTP {status} — unavailable")
        return None
    if body[:4] != b"%PDF":
        print(f"  pdf: not a valid PDF")
        return None

    dest.write_bytes(body)
    print(f"  pdf: saved papers/{filename} ({len(body)/1e6:.1f} MB)")
    return f"papers/{filename}"


# ── Corresponding author extraction ───────────────────────────────────────────
def extract_corresponding_authors(pdf_path, authors):
    """
    Extract corresponding authors from PDF first page using pdftotext.
    Looks for author names followed by * marker.
    Falls back to last author (physics convention) if no * found.
    Returns list of dicts: [{"name": ..., "affiliation": ..., "email": ...}]
    """
    if not pdf_path or not Path(pdf_path).exists():
        return _fallback_corresponding(authors)

    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=15
        )
        text = result.stdout
    except Exception as exc:
        print(f"  pdftotext failed: {exc}")
        return _fallback_corresponding(authors)

    if not text.strip():
        print(f"  pdftotext: empty output")
        return _fallback_corresponding(authors)

    # Find authors marked with * in the author line
    # Pattern: name followed by superscript notation containing *
    corresponding = []
    for author in authors:
        # Check if author name appears near a * in the text
        # Handles formats like "Xiaoxue Liu1,2,10*" or "Tingxin Li1,2,10*"
        escaped = re.escape(author)
        # Match name followed by digits/commas then *
        if re.search(rf"{escaped}[\d,†‡¶§]*\*", text):
            corresponding.append({
                "name":        author,
                "affiliation": "",
                "email":       "",
            })

    if corresponding:
        print(f"  corresponding authors (*): {[c['name'] for c in corresponding]}")
        return corresponding

    # Also try last-name only matching for cases like "Liu1,2,10*"
    for author in authors:
        last_name = author.split()[-1]
        if re.search(rf"{re.escape(last_name)}[\d,†‡¶§]*\*", text):
            if not any(c["name"] == author for c in corresponding):
                corresponding.append({
                    "name":        author,
                    "affiliation": "",
                    "email":       "",
                })

    if corresponding:
        print(f"  corresponding authors (last-name match): {[c['name'] for c in corresponding]}")
        return corresponding

    print(f"  no * markers found — falling back to last author")
    return _fallback_corresponding(authors)


def _fallback_corresponding(authors):
    """Fall back to last author as PI per physics convention."""
    if not authors:
        return []
    return [{"name": authors[-1], "affiliation": "", "email": ""}]


# ── Skeleton builder ───────────────────────────────────────────────────────────
def make_skeleton(rec, pdf_path, corresponding_authors):
    return {
        "arxiv_id":              rec["arxiv_id"],
        "openalex_id":           rec.get("openalex_id"),
        "title":                 rec["title"],
        "abstract":              rec["abstract"],
        "authors":               rec["authors"],
        "first_author":          rec["first_author"],
        "arxiv_affiliations":    rec.get("arxiv_affiliations", []),
        "published":             rec["published"],
        "categories":            rec["categories"],
        "doi":                   rec.get("doi"),
        "url":                   rec["url"],
        "pdf_path":              pdf_path,
        "paper_type":            None,
        "materials":             [],
        "corresponding_authors": corresponding_authors,
        "groups":                [],
        "summary_segments":      [],
        "significance_segments": [],
        "enriched":              False,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ensure_dirs()
    papers  = load_papers()
    tracked = existing_ids(papers)

    if TARGET_IDS:
        print(f"TARGET_IDS mode — fetching {len(TARGET_IDS)} paper(s): {TARGET_IDS}")
        raw_papers = query_openalex_by_ids(TARGET_IDS)
    else:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=LOOKBACK_DAYS)
        print(f"Weekly mode — fetching {CATEGORY}: {start.isoformat()} → {today.isoformat()}")
        raw_papers = query_openalex_weekly(start, today)

    new_records = []
    for arxiv_id, work in raw_papers:
        if arxiv_id in tracked:
            print(f"  Skipping {arxiv_id} — already tracked")
            continue
        new_records.append((arxiv_id, parse_work(arxiv_id, work)))

    print(f"\n{len(new_records)} new paper(s) to process")

    added = 0
    for arxiv_id, rec in new_records:
        print(f"\n→ {arxiv_id}: {rec['title'][:65]}...")

        pdf_url  = rec.pop("_pdf_url", None)
        pdf_path = download_pdf(arxiv_id, pdf_url)

        print(f"  extracting corresponding authors...")
        corresponding = extract_corresponding_authors(pdf_path, rec["authors"])

        skeleton = make_skeleton(rec, pdf_path, corresponding)
        papers.append(skeleton)
        tracked.add(arxiv_id)
        added += 1
        save_papers(papers)
        print(f"  saved.")
        time.sleep(1)

    print(f"\nDone. Added {added} paper(s). Total in corpus: {len(papers)}")


if __name__ == "__main__":
    main()
