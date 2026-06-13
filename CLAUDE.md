# CLAUDE.md — 2D Mesoscopic Physics Tracker: Weekly Agent Task

This file defines the complete weekly automated routine. Execute every step in
order. Do not skip or merge steps. Model allocation is mandatory — it is not
a suggestion.

**Google Drive folder:** `1Zru4o_r3wTqeEu55yK88F40b85Q5YlEy`

---

## Model Allocation

| Task | Model |
|---|---|
| Running `fetch_arxiv.py`, link checking, material classification, index building | `claude-sonnet-4-6` |
| Profile biographical research, significance writing, context-layer summaries, affiliation verification | `claude-opus-4-8` |

---

## Step 1 — Fetch New Papers

**Model: `claude-sonnet-4-6`**

```bash
python fetch_arxiv.py
```

The script:
- Queries arXiv for `cond-mat.mes-hall` papers from the past 8 days
- Enriches each with Semantic Scholar metadata (open-access PDF URL, DOI)
- Downloads open-access PDFs to `papers/`
- Writes skeleton records to `metadata/papers.json` (idempotent — skips existing IDs)
- Runs all Tier 2 validation checks at write time; saves after every paper

After running, note:
- How many new papers were added (use this count in the Step 6 commit message)
- Any `needs_review` papers and their failed checks (these surface on the website;
  do not auto-resolve them — leave them for human review)

If Semantic Scholar is unreachable, the script proceeds with arXiv data only.
Log the fallback; do not abort the run.

---

## Step 2 — Enrich Papers

For each paper in `metadata/papers.json` where `enriched: false`, perform the
following sub-steps in order. Save `papers.json` after completing each paper —
do not batch-save only at the end.

### 2a — Material Classification

**Model: `claude-sonnet-4-6`**

Read `title` and `abstract`. Set `materials` as a list of normalized strings.
Use only the canonical names below. If a material clearly present in the paper
is not listed, add it in the same style (lowercase, spaces).

| Canonical name | Variants it covers |
|---|---|
| `graphene` | monolayer graphene, single-layer graphene, SLG |
| `bilayer graphene` | AB-stacked bilayer graphene, Bernal bilayer, BLG |
| `twisted bilayer graphene` | TBG, magic-angle graphene, MATBG |
| `twisted trilayer graphene` | TTG, alternating-twist trilayer |
| `MoTe2` | molybdenum ditelluride (untwisted) |
| `twisted MoTe2` | moiré MoTe2, tMoTe2, t-MoTe2 |
| `WSe2` | tungsten diselenide |
| `WS2` | tungsten disulfide |
| `MoS2` | molybdenum disulfide |
| `MoSe2` | molybdenum diselenide |
| `hBN` | hexagonal boron nitride, h-BN, BN |
| `TMD` | generic transition metal dichalcogenide (use specific name when possible) |
| `2DEG` | two-dimensional electron gas, GaAs/AlGaAs heterostructure |
| `InAs` | indium arsenide quantum well |
| `InSb` | indium antimonide |
| `topological insulator` | Bi₂Se₃, Bi₂Te₃, and related TI compounds |
| `quantum dot` | single quantum dot, double quantum dot, QD array |
| `quantum spin Hall` | QSH insulator, helical edge states |
| `Josephson junction` | superconductor–normal–superconductor, SNS, SIS |

If the paper is purely theoretical with no specific material, use `[]`.
If unclear, omit rather than guess.

### 2b — Corresponding Author Identification

**Model: `claude-sonnet-4-6`**

If a PDF exists at `pdf_path`, check the first and last pages for corresponding
author markers (`*`, `†`, email address, or an explicit note).

Populate `corresponding_authors`:
```json
[{"name": "...", "affiliation": "...", "email": "..."}]
```

If no PDF or no clear marker: leave as `[]`. Do not guess.

### 2c — Groups

**Model: `claude-sonnet-4-6`**

Identify the PI(s) whose lab produced the paper. Format: `"PI Name (Institution)"`.

Priority of evidence:
1. Corresponding author (from 2b above)
2. Last author (standard physics convention)
3. Affiliation strings in `arxiv_affiliations`

If none can be reliably identified: leave as `[]`. Do not guess.

### 2d — Summary Segments

**Model: `claude-opus-4-8`**

Write `summary_segments` as a list of segment objects:

```json
{"type": "abstract", "text": "..."}
{"type": "context",  "note": "why this context is relevant", "text": "..."}
```

**Strict rules:**
- `type: "abstract"` — only claims present in the fetched abstract. Do not
  introduce any specific fact (number, material name, technique, novelty claim)
  not in the abstract. Rephrase; do not copy verbatim.
- `type: "context"` — may use your field knowledge. Any specific external claim
  (year, person, paper title, measurement value) must be verifiable or must not
  be stated. When in doubt, drop the specific claim and keep general framing.

Target: 2–3 abstract segments, 1–2 context segments.
Write for a physics PhD audience: concise, no padding.

### 2e — Significance Segments

**Model: `claude-opus-4-8`**

Write `significance_segments` using the same segment structure.

Focus on: why this result matters, what question it advances, what techniques
or platforms it unlocks. Be specific but conservative — do not overstate.

Target: 1–2 segments (typically one abstract-grounded, one context).

### 2f — Mark Enriched

Set `enriched: true`. Save `papers.json`.

---

## Step 3 — Profile Pass

**Model: `claude-opus-4-8`**

Load `metadata/people.json` (create as `[]` if missing).

### 3a — Who needs a profile?

| Criterion | Profile type |
|---|---|
| First or corresponding author in ≥ 2 corpus papers | Full profile |
| All others appearing in corpus | Stub |

Any existing `profile_status: "stub"` who now qualifies for a full profile:
upgrade this run.

### 3b — Stub generation (no research required)

```json
{
  "id": "<lastname_firstname_slugified>",
  "name": "...",
  "institution": null,
  "field": "2D mesoscopic physics",
  "corpus_papers": ["arxiv_id_1", "..."],
  "profile_status": "stub"
}
```

Derive all fields from existing paper metadata only.

### 3c — Full profile generation

Before writing any full profile, you **must** actually search for the following.
Never mark a field `"no_source"` without having genuinely searched for it.

| Required field | Where to look |
|---|---|
| Current institution and title | Lab website, university directory, recent papers |
| Most-cited / landmark paper with full journal reference | Google Scholar, Semantic Scholar |
| Google Scholar profile URL | Google Scholar search |
| PhD institution, year, advisor | Lab website, CV, dissertation acknowledgments |
| Postdoc institution and advisor | Lab website, CV, LinkedIn |

**Three-tier confidence** — apply to every field:
- `"sourced"` — documented at a specific URL; store the URL
- `"estimated"` — derivable from documented evidence; store the derivation logic
- `"no_source"` — only after genuine search returned nothing; never a placeholder

Full profile schema:

```json
{
  "id": "...",
  "name": "...",
  "institution": "...",
  "additional_institutions": [],
  "field": "2D mesoscopic physics",
  "photo_filename": null,
  "photo_path": null,
  "birth_year": null,
  "birth_source": "no_source",
  "birth_note": null,
  "phd_institution": "...",
  "phd_year": null,
  "phd_advisor": "...",
  "phd_thesis": null,
  "phd_source": "sourced",
  "postdoc": [
    {"institution": "...", "advisor": "...", "years": "..."}
  ],
  "postdoc_source": "sourced",
  "career": [
    {"years": "...", "role": "...", "type": "faculty", "source": "sourced", "note": null}
  ],
  "significance": "...",
  "influence": [],
  "rising": false,
  "landmark_papers": [
    {"title": "...", "ref": "full journal citation"}
  ],
  "websites": [
    {"label": "Lab website",    "url": "..."},
    {"label": "Google Scholar", "url": "..."}
  ],
  "last_verified": "<today YYYY-MM-DD>",
  "next_verify":   "<today + 90 days>",
  "changelog": [
    {"date": "...", "note": "Initial profile generated"}
  ],
  "corpus_papers": ["arxiv_id_1", "..."],
  "profile_status": "full"
}
```

**`significance`** — 2–4 sentences. Ground in verifiable outputs (papers,
techniques, platforms). Use your field knowledge but state no specific
unverifiable fact.

**`rising`** — set `true` for researchers within ~5 years of first faculty
position who show strong evidence of high-impact work. Counteracts seniority
bias in the corpus.

### 3d — Affiliation change detection

For each new paper, compare `arxiv_affiliations` against the stored
`institution` in that author's existing profile.

On mismatch:
1. Do **not** update `institution` automatically
2. Append to `changelog`: `"Possible affiliation change: paper ARXIV_ID lists 'NEW_INSTITUTION'"`
3. Search primary sources (lab website, university directory) to verify
4. Only update `institution` if the new affiliation is confirmed by a primary source

One data point is not proof of a move.

### 3e — Quarterly re-verification rotation

Each weekly run, re-verify a rotating subset of full profiles.
Target: 5% of full profiles per run (≈ full cycle every 5 months).

Select profiles: sort by `next_verify` ascending, take top N where:
```
N = max(1, round(0.05 × number_of_full_profiles))
```

Re-verification checklist:
1. Confirm current institution and title
2. Confirm lab website URL is live
3. Log any changes in `changelog` with today's date
4. Set `last_verified` = today
5. Set `next_verify` = today + 90 days

---

## Step 4 — Build Indexes

**Model: `claude-sonnet-4-6`**

```bash
python build_indexes.py
```

Regenerates:
- `indexes/by_material.md`
- `indexes/by_group.md`
- `indexes/by_first_author.md`
- `metadata/manifest.json` (preserves existing Drive IDs)

If `papers.json` is malformed, fix it before re-running. Do not proceed to
Step 5 if this step errors.

---

## Step 5 — Upload to Google Drive

**Model: `claude-sonnet-4-6`**

Use the Google Drive MCP. Upload to folder ID `1Zru4o_r3wTqeEu55yK88F40b85Q5YlEy`.

Upload in this order. After each metadata file, record the returned Drive file
ID into `manifest.json`.

| Local path | Drive destination | Manifest key to update |
|---|---|---|
| `metadata/papers.json` | `metadata/papers.json` | `files.papers_json.gdrive_id` |
| `metadata/people.json` | `metadata/people.json` | `files.people_json.gdrive_id` |
| `indexes/by_material.md` | `indexes/by_material.md` | — |
| `indexes/by_group.md` | `indexes/by_group.md` | — |
| `indexes/by_first_author.md` | `indexes/by_first_author.md` | — |
| `papers/*.pdf` (new PDFs only) | `papers/*.pdf` | — |

After recording the IDs for `papers.json` and `people.json` into `manifest.json`,
upload `manifest.json` itself:

| `metadata/manifest.json` | `metadata/manifest.json` | `files.manifest_json.gdrive_id` |

Then update `manifest.json` with its own Drive ID and re-upload once more.

---

## Step 6 — Commit

From the repo root, using N = the count of new papers from Step 1 output:

```bash
git add metadata/ indexes/ papers/
git commit -m "weekly update $(date +%Y-%m-%d): N new papers"
```

---

## Open-Access Policy

Never attempt to access paywalled content. For paywalled papers:
- Store all metadata (title, authors, abstract, DOI, arXiv ID)
- Write `summary_segments` and `significance_segments` from the abstract only
- Set `pdf_path: null`
- The website surfaces these as "PDF needed" with the expected filename:
  `{arxiv_id_with_slashes_replaced_by_underscores}.pdf`

---

## Validation Queue

Papers with `validation.status == "needs_review"` are shown on the website for
human review. Do not auto-resolve. After human inspection, update `validation`
manually and set `status` to `"pass"` or document the confirmed issue.

---

## Error Handling

| Situation | Action |
|---|---|
| Semantic Scholar unreachable | Proceed with arXiv data only; log fallback |
| PDF download fails | Set `pdf_path: null`; skip `pdf_title_match` check; continue |
| Profile search returns nothing | Use `"no_source"` tag after genuine search; do not fabricate |
| `build_indexes.py` errors | Fix `papers.json` before re-running; do not commit broken indexes |
| Any Step 1–4 error unresolved | Do not proceed to Step 6 |

---

## Historical Backfill (Manual — Not Part of Weekly Run)

The weekly routine pulls the past 8 days only. Backfill is triggered manually:

| Phase | Scope | Method |
|---|---|---|
| 1 | ~50 landmark papers | Manual curation |
| 2 | Nature, Science, Nature Physics, Nature Materials, Nature Electronics — past 5 years | Small batches |
| 3 | PRL and PRB — keyword-filtered | Gradual ingestion |
| 4 | Full arXiv on-demand | Triggered by conversation or profile need |

To run backfill: adjust `LOOKBACK_DAYS` in `fetch_arxiv.py` or modify the arXiv
query date range directly. Idempotency guarantees re-running over already-ingested
papers is safe.
