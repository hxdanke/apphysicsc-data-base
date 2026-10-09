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

Reseed the bank from a PDF at any time:

```bash
python scripts/seed_from_pdf.py "path/to/book.pdf" --doc-id EB3 --dpi 300 --replace
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

### 3. Import (扩充题库)
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
  bank.json        # every question (git-friendly, diffable)
  taxonomy.json    # 7 units / 41 topics (AP Physics C: Mechanics CED order)
  media/*.png      # figures referenced by the LaTeX bodies
ingest/<job>/      # drafts from the import UI (gitignored)
exports/           # generated .tex / .pdf (gitignored)
```

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

## Syncing to GitHub

The repository is initialised and committed locally on `main`:

```bash
git remote add origin git@github.com:<you>/ap-physics-c-mechanics-question-bank.git
git push -u origin main
```

(The bundled GitHub connector has read-only scope here and cannot create repositories,
so the remote has to be added by hand — or push with a PAT that has `repo` scope.)

## Known limitations (v0.1)

* **No answer key.** Exercise Book 3 has none, so `answer` / `solution` are empty; the
  UI surfaces them but there is nothing to show yet.
* **Deterministic conversion is typographic, not semantic.** Stacked fractions
  (`\frac{a}{b}`), radicals spanning several spans and a handful of table-layout
  questions come out rough. **35 questions are flagged `needs_review`** — filter by
  that flag and fix or AI-polish them.
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
scripts/       offline seeding / maintenance
```
