#!/usr/bin/env python3
"""
fetch_arxiv.py — Deterministic ingestion for the 2D mesoscopic physics tracker.

Pure standard library. No pip. Idempotent — skips already-tracked arXiv IDs.
Discovery: arXiv API (cond-mat.mes-hall, past 8 days).
Enrichment: Semantic Scholar per-paper lookup for open-access PDF URLs and DOI.
Downloads open-access PDFs. Writes skeleton records to metadata/papers.json.
Runs Tier 2 validation at write time.
"""

import datetime
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
CATEGORY       = "cond-mat.mes-hall"
LOOKBACK_DAYS  = 8
MAX_RESULTS    = 200          # arXiv results per query

BASE_DIR       = Path(__file__).parent
METADATA_DIR   = BASE_DIR / "metadata"
PAPERS_DIR     = BASE_DIR / "papers"
PAPERS_JSON    = METADATA_DIR / "papers.json"

ARXIV_API      = "http://export.arxiv.org/api/query"
ARXIV_ABS      = "https://arxiv.org/abs"
ARXIV_PDF      = "https://arxiv.org/pdf"
S2_API         = "https://api.semanticscholar.org/graph/v1"

USER_AGENT     = "2DMesoscopicTracker/1.0 (research; contact via GitHub)"
S2_FIELDS      = "externalIds,openAccessPdf,publicationDate,authors,journal"


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


# ── HTTP helpers ───────────────────────────────────────────────────────────────
def _request(url, method="GET", timeout=30):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.status
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except Exception:
        return None, 0


def fetch(url, timeout=30):
    body, status = _request(url, timeout=timeout)
    return body, status


def head_status(url, timeout=15):
    _, status = _request(url, method="HEAD", timeout=timeout)
    return status


# ── arXiv discovery ────────────────────────────────────────────────────────────
def _arxiv_date_window(start, end):
    """Return arXiv submittedDate range string."""
    s = start.strftime("%Y%m%d") + "000000"
    e = end.strftime("%Y%m%d") + "235959"
    return f"[{s}+TO+{e}]"


def query_arxiv(start_date, end_date):
    """
    Fetch cond-mat.mes-hall papers submitted in [start_date, end_date].
    Returns list of raw paper dicts (Tier 1 fields only — from API).
    """
    window = _arxiv_date_window(start_date, end_date)
    search = f"cat:{CATEGORY}+AND+submittedDate:{window}"
    params = urllib.parse.urlencode({
        "search_query": search,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": MAX_RESULTS,
    })
    url = f"{ARXIV_API}?{params}"
    body, status = fetch(url, timeout=45)
    if status != 200 or not body:
        print(f"  [arXiv] HTTP {status} — no results")
        return []
    papers = _parse_arxiv_xml(body.decode("utf-8"))
    print(f"  [arXiv] {len(papers)} papers returned")
    return papers


def _parse_arxiv_xml(xml_text):
    ns = {
        "atom":  "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall("atom:entry", ns):
        raw_id = (entry.findtext("atom:id", "", ns) or "").split("/abs/")[-1].strip()
        base_id   = re.sub(r"v\d+$", "", raw_id)
        version_id = raw_id

        title    = " ".join((entry.findtext("atom:title",   "", ns) or "").split())
        abstract = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
        published = (entry.findtext("atom:published", "", ns) or "")[:10]

        authors = [
            a.findtext("atom:name", "", ns)
            for a in entry.findall("atom:author", ns)
        ]
        affiliations = [
            a.findtext("arxiv:affiliation", "", ns)
            for a in entry.findall("atom:author", ns)
            if a.findtext("arxiv:affiliation", "", ns)
        ]
        categories = [
            c.get("term", "") for c in entry.findall("atom:category", ns)
        ]
        doi = entry.findtext("arxiv:doi", "", ns) or None

        if not base_id or not title:
            continue

        out.append({
            "arxiv_id":          base_id,
            "version_id":        version_id,
            "title":             title,
            "abstract":          abstract,
            "authors":           [a for a in authors if a],
            "first_author":      authors[0] if authors else "",
            "arxiv_affiliations": affiliations,
            "published":         published,
            "categories":        categories,
            "doi":               doi,
            "url":               f"{ARXIV_ABS}/{base_id}",
            "_s2_pdf_url":       None,
        })
    return out


# ── Semantic Scholar enrichment (per-paper lookup) ─────────────────────────────
def enrich_from_s2(arxiv_id):
    """
    Look up a single paper on S2 by arXiv ID.
    Returns (open_access_pdf_url, doi) or (None, None) on failure.
    """
    url = f"{S2_API}/paper/arXiv:{arxiv_id}?fields={S2_FIELDS}"
    body, status = fetch(url, timeout=20)
    if status != 200 or not body:
        return None, None
    data = json.loads(body)
    oa = data.get("openAccessPdf")
    pdf_url = oa.get("url") if oa else None
    doi = (data.get("externalIds") or {}).get("DOI")
    return pdf_url, doi


# ── PDF download ───────────────────────────────────────────────────────────────
def download_pdf(arxiv_id, s2_pdf_url=None):
    """
    Download open-access PDF. Returns relative path string or None.
    Tries S2 URL first, then arXiv direct.
    Never touches paywalled content.
    """
    safe_id  = arxiv_id.replace("/", "_")
    filename = f"{safe_id}.pdf"
    dest     = PAPERS_DIR / filename

    if dest.exists():
        return f"papers/{filename}"

    candidates = []
    if s2_pdf_url:
        candidates.append(s2_pdf_url)
    candidates.append(f"{ARXIV_PDF}/{arxiv_id}")

    for url in candidates:
        body, status = fetch(url, timeout=90)
        if status == 200 and body and body[:4] == b"%PDF":
            dest.write_bytes(body)
            return f"papers/{filename}"
        time.sleep(1)

    return None


# ── Minimal PDF text peek (Tier 2 pdf_title_match) ────────────────────────────
def _pdf_first_page_text(pdf_path):
    """
    Extract a rough text sample from the first 12 KB of a PDF using stdlib only.
    Looks for BT…ET text blocks. Enough to check if title words appear.
    """
    try:
        with open(pdf_path, "rb") as fh:
            raw = fh.read(12288)
        text = raw.decode("latin-1", errors="replace")
        chunks = []
        for block in re.findall(r"BT(.*?)ET", text, re.DOTALL):
            chunks += re.findall(r"\(([^)]{1,200})\)\s*Tj", block)
            for arr in re.findall(r"\[([^\]]{1,400})\]\s*TJ", block):
                chunks += re.findall(r"\(([^)]{1,200})\)", arr)
        return " ".join(chunks)[:3000]
    except Exception:
        return ""


# ── Tier 2 Validation ──────────────────────────────────────────────────────────
def _sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def run_tier2(record):
    """
    Run all six Tier 2 checks. Returns validation dict.
    Sleeps between network calls to stay polite.
    """
    checks = {}
    failed = []
    report = {}

    arxiv_id = record["arxiv_id"]
    title    = record["title"]
    doi      = record.get("doi")
    url      = record.get("url", "")
    authors  = record.get("authors", [])
    published = record.get("published", "")
    pdf_path  = record.get("pdf_path")

    # 1. arxiv_resolves ─────────────────────────────────────────────────────────
    api_url = f"{ARXIV_API}?id_list={arxiv_id}"
    body, status = fetch(api_url, timeout=20)
    time.sleep(1)
    if status == 200 and body:
        fetched = _parse_arxiv_xml(body.decode("utf-8"))
        if fetched and _sim(title, fetched[0]["title"]) >= 0.85:
            checks["arxiv_resolves"] = True
        elif fetched:
            checks["arxiv_resolves"] = False
            failed.append("arxiv_resolves")
            report["arxiv_resolves"] = (
                f"Title mismatch (sim={_sim(title, fetched[0]['title']):.2f}): "
                f"stored='{title[:60]}' api='{fetched[0]['title'][:60]}'"
            )
        else:
            checks["arxiv_resolves"] = False
            failed.append("arxiv_resolves")
            report["arxiv_resolves"] = f"arXiv returned no entry for {arxiv_id}"
    else:
        checks["arxiv_resolves"] = False
        failed.append("arxiv_resolves")
        report["arxiv_resolves"] = f"arXiv API HTTP {status}"

    # 2. doi_matches_title ──────────────────────────────────────────────────────
    if doi:
        doi_url = f"https://doi.org/{doi}"
        body, status = fetch(doi_url, timeout=20)
        time.sleep(1)
        if status == 200 and body:
            page = body.decode("utf-8", errors="replace")
            title_start = title.lower()[:40]
            if title_start in page.lower():
                checks["doi_matches_title"] = True
            else:
                checks["doi_matches_title"] = False
                failed.append("doi_matches_title")
                report["doi_matches_title"] = "Title prefix not found in DOI-resolved page"
        else:
            checks["doi_matches_title"] = False
            failed.append("doi_matches_title")
            report["doi_matches_title"] = f"DOI URL HTTP {status}"
    else:
        checks["doi_matches_title"] = None  # skipped — no DOI

    # 3. pdf_title_match ────────────────────────────────────────────────────────
    if pdf_path and Path(pdf_path).exists():
        text = _pdf_first_page_text(pdf_path)
        title_words = [w for w in title.split() if len(w) >= 5]
        if title_words:
            hit_ratio = sum(1 for w in title_words if w.lower() in text.lower()) / len(title_words)
            checks["pdf_title_match"] = hit_ratio >= 0.5
            if not checks["pdf_title_match"]:
                failed.append("pdf_title_match")
                report["pdf_title_match"] = (
                    f"Only {hit_ratio:.0%} of title words found in PDF first page"
                )
        else:
            checks["pdf_title_match"] = True  # nothing to check
    else:
        checks["pdf_title_match"] = None  # skipped — no PDF

    # 4. links_live ─────────────────────────────────────────────────────────────
    live_failures = []
    ax_status = head_status(url)
    if ax_status not in (200, 301, 302):
        live_failures.append(f"arXiv URL HTTP {ax_status}")
    time.sleep(0.5)
    if doi:
        doi_status = head_status(f"https://doi.org/{doi}")
        if doi_status not in (200, 301, 302):
            live_failures.append(f"DOI URL HTTP {doi_status}")
        time.sleep(0.5)
    if live_failures:
        checks["links_live"] = False
        failed.append("links_live")
        report["links_live"] = "; ".join(live_failures)
    else:
        checks["links_live"] = True

    # 5. authors_complete ───────────────────────────────────────────────────────
    if authors and all(isinstance(a, str) and a.strip() for a in authors):
        checks["authors_complete"] = True
    else:
        checks["authors_complete"] = False
        failed.append("authors_complete")
        report["authors_complete"] = "Authors list empty or contains blank entries"

    # 6. date_valid ─────────────────────────────────────────────────────────────
    try:
        dt = datetime.date.fromisoformat(published)
        if datetime.date(1990, 1, 1) <= dt <= datetime.date.today():
            checks["date_valid"] = True
        else:
            checks["date_valid"] = False
            failed.append("date_valid")
            report["date_valid"] = f"Date {published} outside 1990–today"
    except Exception:
        checks["date_valid"] = False
        failed.append("date_valid")
        report["date_valid"] = f"Unparseable date: '{published}'"

    return {
        "checks": checks,
        "failed": failed,
        "status": "needs_review" if failed else "pass",
        "report": report,
    }


# ── Skeleton builder ───────────────────────────────────────────────────────────
def make_skeleton(base, pdf_path, validation):
    return {
        "arxiv_id":            base["arxiv_id"],
        "version_id":          base.get("version_id", base["arxiv_id"]),
        "title":               base["title"],
        "abstract":            base["abstract"],
        "authors":             base["authors"],
        "first_author":        base["first_author"],
        "arxiv_affiliations":  base.get("arxiv_affiliations", []),
        "published":           base["published"],
        "categories":          base["categories"],
        "doi":                 base.get("doi"),
        "url":                 base["url"],
        "pdf_path":            pdf_path,
        "materials":           [],
        "corresponding_authors": [],
        "groups":              [],
        "summary_segments":    [],
        "significance_segments": [],
        "validation":          validation,
        "enriched":            False,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ensure_dirs()
    papers  = load_papers()
    tracked = existing_ids(papers)

    today = datetime.date.today()
    start = today - datetime.timedelta(days=LOOKBACK_DAYS)
    print(f"Fetching {CATEGORY} papers: {start.isoformat()} → {today.isoformat()}")

    # Step 1: Discover via arXiv (category-accurate)
    raw_papers = query_arxiv(start, today)

    # Step 2: Enrich each with Semantic Scholar metadata
    new_records = []
    for p in raw_papers:
        if p["arxiv_id"] in tracked:
            continue
        print(f"  [S2 lookup] {p['arxiv_id']}")
        s2_pdf, s2_doi = enrich_from_s2(p["arxiv_id"])
        time.sleep(0.5)
        if s2_pdf:
            p["_s2_pdf_url"] = s2_pdf
        if s2_doi and not p.get("doi"):
            p["doi"] = s2_doi
        new_records.append(p)

    print(f"\n{len(new_records)} new papers to process")

    # Step 3: Download PDFs, validate, build skeletons
    added = 0
    for rec in new_records:
        arxiv_id = rec["arxiv_id"]
        print(f"\n→ {arxiv_id}: {rec['title'][:65]}...")

        # PDF
        s2_pdf_url = rec.pop("_s2_pdf_url", None)
        pdf_path   = download_pdf(arxiv_id, s2_pdf_url)
        print(f"  pdf: {pdf_path or 'unavailable'}")

        # Skeleton (needed for validation)
        skeleton = make_skeleton(rec, pdf_path, {})

        # Tier 2 validation
        print("  running Tier 2 validation...")
        validation = run_tier2(skeleton)
        skeleton["validation"] = validation

        if validation["status"] == "needs_review":
            print(f"  ⚠ needs_review — failed: {validation['failed']}")
            for check, msg in validation["report"].items():
                print(f"      {check}: {msg}")
        else:
            print("  ✓ validation passed")

        papers.append(skeleton)
        tracked.add(arxiv_id)
        added += 1
        save_papers(papers)   # save after each paper (crash-safe)
        time.sleep(1)

    print(f"\nDone. Added {added} new papers. Total in corpus: {len(papers)}")


if __name__ == "__main__":
    main()
