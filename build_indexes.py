#!/usr/bin/env python3
"""
build_indexes.py — Regenerates markdown index views and manifest.json.

Reads metadata/papers.json. Writes:
  indexes/by_material.md
  indexes/by_group.md
  indexes/by_first_author.md
  metadata/manifest.json

Google Drive file IDs in manifest.json are populated by the upload step
in CLAUDE.md; this script preserves any already-stored IDs.
"""

import datetime
import json
from collections import defaultdict
from pathlib import Path

BASE_DIR      = Path(__file__).parent
METADATA_DIR  = BASE_DIR / "metadata"
INDEXES_DIR   = BASE_DIR / "indexes"
PAPERS_JSON   = METADATA_DIR / "papers.json"
PEOPLE_JSON   = METADATA_DIR / "people.json"
MANIFEST_JSON = METADATA_DIR / "manifest.json"

GDRIVE_FOLDER_ID = "1Zru4o_r3wTqeEu55yK88F40b85Q5YlEy"
ARXIV_ABS = "https://arxiv.org/abs"


# ── I/O helpers ────────────────────────────────────────────────────────────────
def ensure_dirs():
    INDEXES_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def write_text(path, content):
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ {path.relative_to(BASE_DIR)}")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  ✓ {path.relative_to(BASE_DIR)}")


# ── Paper formatting ───────────────────────────────────────────────────────────
def paper_line(p):
    """Single markdown list item for a paper."""
    arxiv_id = p["arxiv_id"]
    title    = p.get("title", "(no title)")
    authors  = p.get("authors", [])
    first    = p.get("first_author") or (authors[0] if authors else "Unknown")
    et_al    = " et al." if len(authors) > 1 else ""
    date     = p.get("published", "")
    url      = p.get("url") or f"{ARXIV_ABS}/{arxiv_id}"
    flag     = " ⚠" if p.get("validation", {}).get("status") == "needs_review" else ""
    pdf_note = "" if p.get("pdf_path") else " · _PDF needed_"
    return (
        f"- [{title}]({url}) — "
        f"{first}{et_al} ({date}){flag}{pdf_note} `{arxiv_id}`"
    )


def section_header(title, count):
    return f"## {title} ({count})\n"


def page_header(heading, total):
    today = datetime.date.today().isoformat()
    return (
        f"# {heading}\n\n"
        f"_Generated {today} · {total} total papers_\n"
    )


def sort_by_date_desc(papers):
    return sorted(papers, key=lambda x: x.get("published", ""), reverse=True)


# ── by_material.md ─────────────────────────────────────────────────────────────
def build_by_material(papers):
    by_mat = defaultdict(list)
    unclassified = []

    for p in papers:
        mats = p.get("materials") or []
        if mats:
            for m in mats:
                by_mat[m].append(p)
        else:
            unclassified.append(p)

    lines = [page_header("Papers by Material System", len(papers))]

    for mat in sorted(by_mat, key=str.lower):
        group = sort_by_date_desc(by_mat[mat])
        lines.append(section_header(mat, len(group)))
        lines += [paper_line(p) for p in group]
        lines.append("")

    if unclassified:
        group = sort_by_date_desc(unclassified)
        lines.append(section_header("Unclassified", len(group)))
        lines += [paper_line(p) for p in group]
        lines.append("")

    return "\n".join(lines)


# ── by_group.md ────────────────────────────────────────────────────────────────
def build_by_group(papers):
    by_group = defaultdict(list)
    no_group = []

    for p in papers:
        groups = p.get("groups") or []
        if groups:
            for g in groups:
                by_group[g].append(p)
        else:
            no_group.append(p)

    lines = [page_header("Papers by Research Group", len(papers))]

    for group in sorted(by_group, key=str.lower):
        ps = sort_by_date_desc(by_group[group])
        lines.append(section_header(group, len(ps)))
        lines += [paper_line(p) for p in ps]
        lines.append("")

    if no_group:
        ps = sort_by_date_desc(no_group)
        lines.append(section_header("No Group Assigned", len(ps)))
        lines += [paper_line(p) for p in ps]
        lines.append("")

    return "\n".join(lines)


# ── by_first_author.md ─────────────────────────────────────────────────────────
def _sort_key_author(name):
    parts = name.split()
    return parts[-1].lower() if parts else name.lower()


def build_by_first_author(papers):
    by_author = defaultdict(list)

    for p in papers:
        fa = p.get("first_author") or "Unknown"
        by_author[fa].append(p)

    lines = [page_header("Papers by First Author", len(papers))]

    for author in sorted(by_author, key=_sort_key_author):
        ps = sort_by_date_desc(by_author[author])
        lines.append(section_header(author, len(ps)))
        lines += [paper_line(p) for p in ps]
        lines.append("")

    return "\n".join(lines)


# ── manifest.json ──────────────────────────────────────────────────────────────
def build_manifest(existing):
    """
    Preserve existing Google Drive file IDs; update generation timestamp.
    IDs are written here by the upload step in CLAUDE.md after each upload.
    """
    old_files = existing.get("files", {})

    def keep_id(key):
        return (old_files.get(key) or {}).get("gdrive_id")

    return {
        "gdrive_folder_id": GDRIVE_FOLDER_ID,
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "files": {
            "papers_json": {
                "filename":  "papers.json",
                "path":      "metadata/papers.json",
                "gdrive_id": keep_id("papers_json"),
            },
            "people_json": {
                "filename":  "people.json",
                "path":      "metadata/people.json",
                "gdrive_id": keep_id("people_json"),
            },
            "manifest_json": {
                "filename":  "manifest.json",
                "path":      "metadata/manifest.json",
                "gdrive_id": keep_id("manifest_json"),
            },
        },
    }


# ── Stats summary (printed to stdout) ─────────────────────────────────────────
def print_stats(papers):
    total       = len(papers)
    enriched    = sum(1 for p in papers if p.get("enriched"))
    review      = sum(1 for p in papers if p.get("validation", {}).get("status") == "needs_review")
    no_pdf      = sum(1 for p in papers if not p.get("pdf_path"))
    mat_counts  = defaultdict(int)
    for p in papers:
        for m in (p.get("materials") or []):
            mat_counts[m] += 1

    print(f"\n── Corpus stats ───────────────────────────────────────")
    print(f"  Total papers   : {total}")
    print(f"  Enriched       : {enriched}/{total}")
    print(f"  Needs review   : {review}")
    print(f"  No PDF         : {no_pdf}")
    if mat_counts:
        top = sorted(mat_counts.items(), key=lambda x: -x[1])[:10]
        print(f"  Top materials  : " + ", ".join(f"{m} ({n})" for m, n in top))
    print()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ensure_dirs()

    papers   = load_json(PAPERS_JSON, [])
    existing = load_json(MANIFEST_JSON, {})

    if not papers:
        print("No papers found in metadata/papers.json — nothing to index.")
        return

    print(f"Building indexes from {len(papers)} papers...")

    write_text(INDEXES_DIR / "by_material.md",    build_by_material(papers))
    write_text(INDEXES_DIR / "by_group.md",        build_by_group(papers))
    write_text(INDEXES_DIR / "by_first_author.md", build_by_first_author(papers))
    write_json(MANIFEST_JSON,                       build_manifest(existing))

    print_stats(papers)
    print("Done.")


if __name__ == "__main__":
    main()
