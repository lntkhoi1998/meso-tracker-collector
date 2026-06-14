# CLAUDE.md — 2D Mesoscopic Physics Tracker: Weekly Agent Task

This file defines the complete weekly automated routine. Execute every step in
order. Do not skip or merge steps. Model allocation is mandatory.

---

## Model Allocation

| Task | Model |
|---|---|
| Running `fetch_openalex.py`, material classification, index building | `claude-sonnet-4-6` |
| Profile generation (all fields except significance) | `claude-sonnet-4-6` |
| Profile `significance` field, summary/context segments, significance segments | `claude-opus-4-8` |

---

## Operating Modes

**TARGET_IDS mode** (testing / manual backfill): set `TARGET_IDS = ["arxiv_id", ...]`
in `fetch_openalex.py`. Fetches specific papers by ID, ignores date range. Use this
for testing the pipeline end-to-end on known papers before switching to weekly mode.

**Weekly mode**: set `TARGET_IDS = []` in `fetch_openalex.py`. Fetches all
`cond-mat.mes-hall` papers from the past 8 days via OpenAlex.

---

## Step 1 — Fetch New Papers

**Model: `claude-sonnet-4-6`**

```bash
python fetch_openalex.py
```

In TARGET_IDS mode: fetches the listed arXiv IDs directly from OpenAlex.
In weekly mode: queries OpenAlex for `cond-mat.mes-hall` papers from the past 8 days.

For each new paper:
- Downloads open-access PDF to `papers/` (from OpenAlex pdf_url)
- Extracts corresponding authors from PDF first page (* marker via pdftotext)
- Falls back to last author if no * marker found
- Writes skeleton record to `metadata/papers.json`
- Skips already-tracked arXiv IDs (idempotent)
- Saves after every paper

If OpenAlex is unreachable: fail loudly, do not proceed. No fallbacks.

After running, note how many new papers were added (use this count in the
Step 5 commit message).

---

## Step 2 — Enrich Papers

For each paper in `metadata/papers.json` where `enriched: false`, perform the
sub-steps below in order. Save `papers.json` after each paper.

### 2a — Paper Type Classification

**Model: `claude-sonnet-4-6`**

Read the title and abstract. Set `paper_type` to exactly one of:

| Value | Meaning |
|---|---|
| `"experimental"` | Reports new measurements, device fabrication, or transport/spectroscopy data |
| `"theoretical"` | Proposes or derives a model, computes a prediction, no new experimental data |
| `"review"` | Surveys or synthesizes existing literature |

If genuinely ambiguous: pick the dominant character. Do not leave as `null`.

### 2b — Material Classification

**Model: `claude-sonnet-4-6`**

Read `title` and `abstract`. Set `materials` as a list of normalized strings.
Use only the canonical names below. Add new materials in the same style
(lowercase, spaces) if clearly present and not listed.

| Canonical name | Variants it covers |
|---|---|
| `graphene` | monolayer graphene, SLG |
| `bilayer graphene` | AB-stacked, Bernal bilayer, BLG |
| `twisted bilayer graphene` | TBG, magic-angle graphene, MATBG |
| `twisted trilayer graphene` | TTG, alternating-twist trilayer |
| `MoTe2` | molybdenum ditelluride (untwisted) |
| `twisted MoTe2` | moiré MoTe2, tMoTe2, t-MoTe2 |
| `WSe2` | tungsten diselenide |
| `WS2` | tungsten disulfide |
| `MoS2` | molybdenum disulfide |
| `MoSe2` | molybdenum diselenide |
| `hBN` | hexagonal boron nitride, h-BN |
| `TMD` | generic TMD (use specific name when possible) |
| `2DEG` | two-dimensional electron gas, GaAs/AlGaAs |
| `InAs` | indium arsenide quantum well |
| `InSb` | indium antimonide |
| `topological insulator` | Bi₂Se₃, Bi₂Te₃, and related TI compounds |
| `quantum dot` | single QD, double QD, QD array |
| `quantum spin Hall` | QSH insulator, helical edge states |
| `Josephson junction` | SNS, SIS junctions |

If purely theoretical with no specific material: use `[]`.
If unclear: omit rather than guess.

### 2c — Groups

**Model: `claude-sonnet-4-6`**

Use `corresponding_authors` already populated by Step 1 (from PDF * markers).
Format each group as `"PI Name (Institution)"`.

If `corresponding_authors` is empty: use last author per physics convention.
If institution is unknown: use `"PI Name (Unknown Institution)"`.
Do not guess institutions.

### 2d — Summary Segments

**Model: `claude-opus-4-8`**

```json
{"type": "abstract", "text": "..."}
{"type": "context",  "note": "why this context is relevant", "text": "..."}
```

- `type: "abstract"` — only claims present in the fetched abstract.
  Do not introduce any specific fact not in the abstract. Rephrase; do not copy verbatim.
- `type: "context"` — may use your field knowledge. Any specific external claim
  (year, person, paper, value) must be verifiable or must not be stated.

Target: 2–3 abstract segments, 1–2 context segments.
Audience: physics PhD. Concise, no padding.

### 2e — Significance Segments

**Model: `claude-opus-4-8`**

Same segment structure as 2d.
Focus: why this result matters, what question it advances, what it opens up.
Be specific but conservative — do not overstate.
Target: 1–2 segments.

### 2f — Mark Enriched

Set `enriched: true`. Save `papers.json`.

---

## Step 3 — Profile Pass

Load `metadata/people.json` (create as `[]` if missing).

### 3a — Who gets a profile?

Only two categories:

| Category | Definition | Profile type |
|---|---|---|
| First author | Listed as first author on any corpus paper | Full profile |
| PI | In `corresponding_authors` on any corpus paper | Full profile |

Everyone else gets no profile entry at all.

### 3b — Full profile generation

**Model: `claude-sonnet-4-6`** for all fields except `significance`.
**Model: `claude-opus-4-8`** for the `significance` field only.

Before writing any profile, you **must** actually search for the following.
Never mark a field `"no_source"` without having genuinely searched.

| Required | Where to look |
|---|---|
| Current institution and title | Lab website, university directory, recent papers |
| Most-cited / landmark paper with full journal reference | Google Scholar, Semantic Scholar |
| Google Scholar profile URL | Google Scholar search |
| PhD institution, year, advisor | Lab website, CV, dissertation acknowledgments |
| Postdoc institution and advisor | Lab website, CV, LinkedIn |

**Three-tier confidence** on every field:
- `"sourced"` — documented at a specific URL; store the URL
- `"estimated"` — derivable from documented evidence; store the derivation
- `"no_source"` — only after genuine search returned nothing

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
  "postdoc": [{"institution": "...", "advisor": "...", "years": "..."}],
  "postdoc_source": "sourced",
  "career": [
    {"years": "...", "role": "...", "type": "faculty", "source": "sourced", "note": null}
  ],
  "significance": "...",
  "influence": [],
  "rising": false,
  "landmark_papers": [{"title": "...", "ref": "full journal citation"}],
  "websites": [
    {"label": "Lab website",    "url": "..."},
    {"label": "Google Scholar", "url": "..."}
  ],
  "last_verified": "<today YYYY-MM-DD>",
  "next_verify":   "<today + 90 days>",
  "changelog": [{"date": "...", "note": "Initial profile generated"}],
  "corpus_papers": ["arxiv_id_1"],
  "profile_status": "full"
}
```

**`significance`** (Opus 4.8) — 2–4 sentences grounded in verifiable outputs.
Use field knowledge but state no specific unverifiable fact.

**`rising`** — set `true` for researchers within ~5 years of first faculty
position with strong evidence of high-impact work.

### 3c — Affiliation change detection

For each new paper, compare `arxiv_affiliations` against stored `institution`.

On mismatch:
1. Do **not** update `institution` automatically
2. Append to `changelog`: `"Possible affiliation change: paper ARXIV_ID lists 'NEW_INSTITUTION'"`
3. Search primary sources to verify
4. Only update if confirmed by a primary source

### 3d — Quarterly re-verification rotation

Each weekly run: re-verify top N profiles by `next_verify` ascending, where:
```
N = max(1, round(0.05 × number_of_full_profiles))
```

Re-verification: confirm institution, confirm website is live, log changes,
set `last_verified` = today, set `next_verify` = today + 90 days.

---

## Step 4 — Build Indexes

**Model: `claude-sonnet-4-6`**

```bash
python build_indexes.py
```

Regenerates `indexes/by_material.md`, `indexes/by_group.md`,
`indexes/by_first_author.md`.

Fix `papers.json` before re-running if this errors. Do not proceed to Step 5
if this step fails.

---

## Step 5 — Commit and Push to GitHub

**Model: `claude-sonnet-4-6`**

```bash
git add metadata/ indexes/ papers/
git commit -m "weekly update $(date +%Y-%m-%d): N new papers"
git push origin main
```

Where N is the count of new papers from Step 1 output.

The website reads `papers.json` and `people.json` directly from GitHub raw URLs —
no upload step needed. Everything is live as soon as the push completes.

---

## Open-Access Policy

Never access paywalled content. For paywalled papers: store all metadata,
set `pdf_path: null`. Website surfaces these as "PDF needed" with the expected
filename: `{arxiv_id}.pdf`.

---

## Error Handling

| Situation | Action |
|---|---|
| OpenAlex unreachable | Fail loudly — do not proceed, no fallbacks |
| PDF download fails | Set `pdf_path: null`; continue |
| No * marker in PDF | Fall back to last author as PI |
| Profile search returns nothing | Use `"no_source"` after genuine search; do not fabricate |
| `build_indexes.py` errors | Fix `papers.json` first; do not commit broken indexes |
| Any Step 1–4 error unresolved | Do not push to GitHub |

---

## Historical Backfill (Manual — Not Part of Weekly Run)

Use TARGET_IDS mode in `fetch_openalex.py` for on-demand ingestion of specific
papers (landmark results, papers from conversations, profile needs). The
idempotency guarantee means re-running over already-ingested papers is safe.

Phased bulk backfill (triggered manually):

| Phase | Scope |
|---|---|
| 1 | ~50 landmark papers, manually curated |
| 2 | Nature, Science, Nature Physics, Nature Materials, Nature Electronics — past 5 years |
| 3 | PRL and PRB — keyword-filtered, gradual |
| 4 | Full arXiv on-demand |
