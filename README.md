# AP Physics C: Mechanics — Question Bank

A local web app for browsing, assembling and exporting AP Physics C: Mechanics
questions. Every question is stored as **LaTeX** (with its figures kept as real image
files), so a practice set can be exported as a `.tex` file or compiled straight to PDF.

> **Status: v0.1 — first draft.** The bank is seeded with all **369 questions** of
> *Exercise Book 3 – Topic Questions 2026-2027* (7 units / 41 topics, 184 figures).
> The deterministic PDF→LaTeX converter is good but not perfect; see
> [Known limitations](#known-limitations).

---

## Quick start

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8765
# or: ./run.sh   /   run.bat
```

Open <http://127.0.0.1:8765>.

### Courses

Four courses are served, each with **its own independent bank**. A question in
one course is invisible to the others, and a paper never spans courses — switch
with the dropdown on the course name, top left.

| course id | name |
|---|---|
| `apc-mech` | AP Physics C: Mechanics |
| `apc-em` | AP Physics C: Electricity and Magnetism |
| `ap1` | AP Physics 1 |
| `ap2` | AP Physics 2 |

AP Physics C: Mechanics keeps the original `data/bank.json`; the others live
under `data/banks/<course>/`. Figures share `data/media/` with course-prefixed
filenames. The three newer courses ship a taxonomy and one sample question —
regenerate them with `python scripts/init_courses.py` (add `--force` to overwrite).

### Sign-in

On first run an `admin` account is created automatically with the password
`admin` — **change it under Account right away** (or set `QB_ADMIN_PASSWORD`
before the first start). Admins create the teacher accounts under the **Users**
tab.

Set `QB_REQUIRE_LOGIN=0` to run without sign-in (a private, one-person
install); everything is then attributed to the admin account, so saved papers
still have an owner.

```bash
# optional configuration
export QB_APP_DB=data/app.sqlite      # where accounts and saved papers live
export QB_REQUIRE_LOGIN=1             # 0 disables sign-in
export QB_ADMIN_USERNAME=admin
export QB_ADMIN_PASSWORD=...
```

Reseed the bank from a PDF at any time, then repair the extracted LaTeX:

```bash
python scripts/seed_from_pdf.py "path/to/book.pdf" --doc-id EB3 --dpi 300 --replace
python scripts/normalize_bank.py            # dry run: report what would change
python scripts/normalize_bank.py --apply    # rewrite data/bank.json (keeps a .bak)
```

---

## What it does

### 1. Browse
Sidebar tree **Unit → Topic → question**. KaTeX renders the LaTeX live in the browser;
figures are served from `data/media/`. Search box, "needs review" and "no difficulty"
filters, per-question LaTeX viewer.

### 2. Compose (组卷)
Add questions to the paper (individually or a whole topic at once), drag to reorder,
set a title / subtitle / instructions, choose whether to include answers and solutions,
then:

* **LaTeX source** — downloads a standalone, compilable `.tex` document.
* **Compile PDF** — runs a TeX engine on the server and downloads the PDF.

Figures are referenced with `\includegraphics`, `\graphicspath` is set automatically.

A practice set is **the questions and nothing else**. The generated PDF is A4,
**Times New Roman 11pt** throughout: the typeface is mapped onto the maths alphabets as
well, so quantities are set in Times New Roman *Italic*, units and multi-letter labels
upright (`a_{x}` italic, `a_{\mathrm{avg}}` upright); only the symbols Times New Roman
has no glyph for — integral, radical, sigma — come from Cambria Math. There is no cover
title, no unit or topic heading, no page number, no running head or foot, and no
provenance line under a question; the numbering runs straight through from 1. Short
multiple-choice options are set inline on one line, long ones (or ones carrying a
figure) as a list. These are set in `_HEAD` / `_FONTS_XE` in `server/latex.py`.

The browser renders the same data with KaTeX, and `web/css/app.css` pins the same
typeface there, so what you preview is what the PDF prints.

### 3. My Papers (保存与共享试卷)

A selection lives only in the browser tab until you save it. **My Papers** stores
it under your account: the ordered question ids plus the export options, so
reopening a paper restores Compose exactly as you left it.

* **Save selection** — captures what Compose is currently showing.
* **Open** — loads a saved paper back into Compose.
* **Share** — publish it to a sharing group and/or individual colleagues.

Sharing is deliberately one-directional and frozen at publish time:

* each publish writes an **immutable revision**; editing your own copy afterwards
  never changes what a colleague already received;
* re-publishing unchanged content is rejected instead of producing a duplicate
  version;
* recipients can read, build and **Save a copy**, but never edit the owner's draft;
* private book-keeping (`question_exclusions`) is stripped before publishing.

### 4. Users (管理员)

Admins create teacher accounts, reset passwords, disable accounts and read the
activity log. At least one active admin is always required.

### 5. New question (自己编题)

Build a question without a PDF. The stem is a list of **blocks** — text and
figures in whatever order you want, each one moveable and removable:

* a **text block** holds LaTeX, as typed;
* an **image block** takes an uploaded figure, its width and an optional caption.
  Leave it empty and it renders as a visible placeholder, so a half-finished
  question looks half-finished rather than quietly missing a figure.

The blocks are the editable form; the LaTeX `stem` the paper uses is derived from
them, which is why a hand-written question composes into a paper exactly like an
imported one. Editing the LaTeX directly drops the blocks.

You must file the question under at least one **knowledge block** (see below).

### 6. Knowledge blocks

A question is filed under a primary unit/topic, and may also list
**additional topics** — the other blocks it draws on. A question about a
collision that needs energy conservation can be found from either side, and
filtering by a topic matches questions that list it as primary *or* additional.

Both the authoring form and the **Knowledge blocks** button on any existing
question open the same multi-select picker; the first box you tick is the primary.

### 7. Tags (标签)

Any question can carry as many tags as you like. Tags are free text, but the
editor offers every tag already used in that course, so a tag gets reused rather
than retyped three different ways — the list *is* the vocabulary.

* type a new tag and press Enter, or click one of the suggestions;
* click **×** on a tag to remove it, or Backspace in the empty box to undo the
  last one;
* tags are matched by the search box, so typing a tag finds its questions;
* each course keeps its own vocabulary.

Tags are pure metadata: they never appear in the compiled paper.
`scripts/tag_all.py` adds or removes one tag across a whole course, and runs dry
by default:

```bash
python scripts/tag_all.py --course apc-mech --tag "Topic Questions"          # dry run
python scripts/tag_all.py --course apc-mech --tag "Topic Questions" --apply
```

### 8. Recycle Bin (回收站)

Deleting a question asks for confirmation, then moves it to the per-course
Recycle Bin instead of destroying it. There it keeps its whole body and can be:

* **restored** back into the bank, or
* **deleted permanently** by hand, or
* left alone — after **30 days** it is dropped automatically.

The retention sweep runs whenever the bin is read, so it needs no scheduled job.

### 9. Import (扩充题库)
Upload a PDF → the server extracts text, sub/superscripts, figures (rendered at the
chosen DPI) and the unit/topic structure → you get a **draft** to review → optional
**AI polish** → **commit** to the bank.

The AI step is the "hook into the model" part: set `AI_API_KEY` (+ optional
`AI_BASE_URL`, `AI_MODEL`, see `.env.example`) and each draft question is sent to an
OpenAI-compatible chat endpoint with a strict JSON contract, asking for clean LaTeX
while preserving every `\includegraphics` path. Without a key the pipeline still works
and simply keeps the deterministic draft.

---

## Data layout

```
data/
  bank.json        # AP Physics C: Mechanics (git-friendly, diffable)
  taxonomy.json    # its 7 units / 41 topics (AP Physics C: Mechanics CED order)
  media/*.png      # figures referenced by the LaTeX bodies, all courses
  banks/<course>/  # bank.json + taxonomy.json for the other three courses
  app.sqlite       # accounts, saved papers, sharing, activity log (gitignored)
  recycled.json    # recycle bin, transient (gitignored)
ingest/<job>/      # drafts from the import UI (gitignored)
exports/           # generated .tex / .pdf (gitignored)
```

Question **content** stays in the bank JSON files; `app.sqlite` is server-owned
live state and is never edited by hand. Keeping them apart means reseeding a bank
never touches who can sign in or which papers teachers saved. The data root can
be relocated with `QB_DATA_DIR` (the tests use this to run against a throw-away
tree).

A question looks like this (trimmed):

```json
{
  "id": "EB3-U1-1.1-Q1",
  "unit": 1, "unit_title": "Kinematics",
  "topic": "1.1", "topic_title": "Scalars and Vectors",
  "number": 1, "qtype": "mcq",
  "stem": "The $x$- and $y$-components ... $a_{x}\\ = (t\\ -\\ 6) \\mathrm{m/s}^{2}$ ...",
  "choices": [{"label": "A", "text": "$1 \\mathrm{m/s}^{2}$"}, ...],
  "answer": "", "solution": "", "difficulty": "", "tags": [],
  "images": [{"file": "u1_11_q7_5.png", "rel": "media/u1_11_q7_5.png", "width": 0.21}],
  "source": {"doc": "EB3", "pdf_page": 7, "book_page": 1},
  "layout": "inline", "needs_review": false
}
```

Editing is possible through `PATCH /api/questions/{id}`.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | engine detection, AI status, bank stats |
| GET | `/api/taxonomy` | units / topics with counts |
| GET | `/api/questions?q=&unit=&topic=&needs_review=&untagged=` | search |
| GET | `/api/questions/{id}` · `/tex` | one question / its standalone LaTeX |
| PATCH · DELETE | `/api/questions/{id}` | edit · remove |
| POST | `/api/export/latex` · `/file` | `.tex` as JSON / as a download |
| POST | `/api/export/pdf` | compile and download a PDF |
| POST | `/api/ingest` | upload a PDF, run extraction |
| GET | `/api/ingest` · `/api/ingest/{job}` | list / inspect drafts |
| POST | `/api/ingest/{job}/polish` · `/commit` | AI polish · merge into the bank |

---

## PDF compilation

The server looks for `tectonic`, `xelatex`, `lualatex` or `pdflatex` on `PATH`, plus a
vendored `tools/tectonic.exe`. If none is found, **LaTeX export still works** and
"Compile PDF" returns a clear message.

Recommended: [tectonic](https://tectonic-typesetting.github.io/) — a single binary that
fetches packages on demand. Drop it into `tools/` or put it on your `PATH`.

---

## Tests

```bash
python -m pytest
```

The suite covers the account layer (password hashing, sessions, expiry, activity
log), the paper layer (draft ownership, version conflicts, append-only
revisions, notifications) and the HTTP surface end to end (routes locked until
sign-in, cross-teacher isolation, stale-tab rejection). Database tests each build
a throw-away SQLite file in a temporary directory, so they never touch
`data/app.sqlite`.

## Syncing to GitHub

Work is committed locally on `main`; pushing is done by hand:

```bash
git remote add origin git@github.com:<you>/apphysicsc-data-base.git   # once
git push -u origin main
```

## Known limitations (v0.1)

* **No answer key.** Exercise Book 3 has none, so `answer` / `solution` are empty; the
  UI surfaces them but there is nothing to show yet.
* **Deterministic conversion is typographic, not semantic.** Stacked fractions
  (`\frac{a}{b}`), radicals spanning several spans and a handful of table-layout
  questions come out rough. **A few questions are flagged `needs_review`** — filter by
  that flag and fix or AI-polish them.
* **Three option cells are still garbled.** Stacked formulas whose fraction bar *and*
  base are both missing from the PDF text layer cannot be reconstructed:
  `EB3-U1-1.5-Q9 D`, `EB3-U5-5.1-Q2 D`, `EB3-U6-6.5-Q3 D`. Everything else renders — the
  KaTeX error count across 1 829 bank fields is 3, down from 90.
* **LaTeX is hardened before export.** `server/latex.py` (`tex_safe`) and
  `scripts/texfix.py` repair the extraction artefacts that also break a real TeX engine:
  cascaded scripts (`v^{0}^{t}^{cos}`), glued macro names (`\Deltat`), units detached
  from their value (`4 m/s 45°`, not `4 m/s45°`), a base letter the extractor left
  outside the maths run (`a$x$` -> `$a_{x}$`), multi-letter subscripts set upright,
  stray braces and unpaired `$`. Without this a single bad question aborts the whole
  export. `seed_from_pdf.py` runs the same repairs, so a re-import needs no extra step.
* Figures are captured from the page at the chosen DPI; a figure that the book places
  *above* the question referring to it is re-attached by a heuristic, which can
  occasionally be off by one.
* Single-user local tool: no auth, bank writes are not transactional beyond an
  atomic file replace.

---

## Layout

```
server/
  extract.py   PDF -> draft questions (reading order, sub/superscripts, figures)
  bank.py      JSON storage, taxonomy, search
  latex.py     LaTeX rendering, engine detection, compilation
  ai.py        optional AI polish (OpenAI-compatible)
  ingest.py    upload -> draft -> review -> commit pipeline
  main.py      FastAPI app
web/           vanilla ES-module SPA + vendored KaTeX (no build step)
scripts/
  seed_from_pdf.py    extract a book into data/bank.json
  texfix.py           LaTeX repair rules (shared by the extractor and the normaliser)
  normalize_bank.py   run texfix over the whole bank, in place
```
