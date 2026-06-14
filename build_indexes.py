#!/usr/bin/env python3
"""
build_indexes.py — Regenerates markdown index views from papers.json.

Reads metadata/papers.json. Writes:
  indexes/by_material.md
  indexes/by_group.md
  indexes/by_first_author.md

All files are committed to GitHub; the website reads them via raw.githubusercontent.com.
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
ARXIV_ABS     = "https://arxiv.org/abs"

TYPE_LABELS = {
    "experimental": "🔬 exp",
    "theoretical":  "📐 theory",
    "review":       "📖 review",
}


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
    arxiv_id = p["arxiv_id"]
    title    = p.get("title", "(no title)")
    authors  = p.get("authors", [])
    first    = p.get("first_author") or (authors[0] if authors else "Unknown")
    et_al    = " et al." if len(authors) > 1 else ""
    date     = p.get("published", "")
    url      = p.get("url") or f"{ARXIV_ABS}/{arxiv_id}"
    flag     = " ⚠" if p.get("validation", {}).get("status") == "needs_review" else ""
    pdf_note = "" if p.get("pdf_path") else " · _PDF needed_"
    ptype    = TYPE_LABELS.get(p.get("paper_type"), "")
    type_str = f" · `{ptype}`" if ptype else ""
    return (
        f"- [{title}]({url}) — "
        f"{first}{et_al} ({date}){flag}{pdf_note}{type_str} `{arxiv_id}`"
    )


def page_header(heading, total):
    today = datetime.date.today().isoformat()
    return f"# {heading}\n\n_Generated {today} · {total} total papers_\n"


def section_header(title, count):
    return f"## {title} ({count})\n"


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
def build_by_first_author(papers):
    by_author = defaultdict(list)
    for p in papers:
        fa = p.get("first_author") or "Unknown"
        by_author[fa].append(p)

    def _key(name):
        parts = name.split()
        return parts[-1].lower() if parts else name.lower()

    lines = [page_header("Papers by First Author", len(papers))]
    for author in sorted(by_author, key=_key):
        ps = sort_by_date_desc(by_author[author])
        lines.append(section_header(author, len(ps)))
        lines += [paper_line(p) for p in ps]
        lines.append("")
    return "\n".join(lines)


# ── Stats ──────────────────────────────────────────────────────────────────────
def print_stats(papers):
    total    = len(papers)
    enriched = sum(1 for p in papers if p.get("enriched"))
    review   = sum(1 for p in papers if p.get("validation", {}).get("status") == "needs_review")
    no_pdf   = sum(1 for p in papers if not p.get("pdf_path"))
    by_type  = defaultdict(int)
    for p in papers:
        by_type[p.get("paper_type") or "unclassified"] += 1

    print(f"\n── Corpus stats ───────────────────────────────────────")
    print(f"  Total      : {total}")
    print(f"  Enriched   : {enriched}/{total}")
    print(f"  Needs review: {review}")
    print(f"  No PDF     : {no_pdf}")
    print(f"  By type    : " + ", ".join(f"{k} ({v})" for k, v in sorted(by_type.items())))
    print()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ensure_dirs()
    papers = load_json(PAPERS_JSON, [])

    if not papers:
        print("No papers found in metadata/papers.json — nothing to index.")
        return

    print(f"Building indexes from {len(papers)} papers...")
    write_text(INDEXES_DIR / "by_material.md",    build_by_material(papers))
    write_text(INDEXES_DIR / "by_group.md",        build_by_group(papers))
    write_text(INDEXES_DIR / "by_first_author.md", build_by_first_author(papers))
    print_stats(papers)
    print("Done.")


if __name__ == "__main__":
    main()
