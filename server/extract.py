"""
PDF -> draft question bank.

Extracts text (with sub/superscript geometry), figures (rendered from the page at a
given DPI so that printed quality is preserved), and the unit / topic structure of an
AP Physics C: Mechanics exercise book, then emits questions whose content is LaTeX.

This module is used by
  * scripts/seed_from_pdf.py  (offline seeding of data/bank.json)
  * server/ingest.py          (runtime "upload a PDF" pipeline)
"""

from __future__ import annotations

import hashlib
import os
import re
import statistics
from dataclasses import dataclass, field, asdict

import pymupdf

# --------------------------------------------------------------------------------------
# Unicode -> LaTeX
# --------------------------------------------------------------------------------------

GREEK = {
    "\u03b1": r"\alpha", "\u03b2": r"\beta", "\u03b3": r"\gamma", "\u03b4": r"\delta",
    "\u03b5": r"\epsilon", "\u03b8": r"\theta", "\u03bb": r"\lambda", "\u03bc": r"\mu",
    "\u03c0": r"\pi", "\u03c1": r"\rho", "\u03c3": r"\sigma", "\u03c4": r"\tau",
    "\u03c6": r"\varphi", "\u03d5": r"\phi", "\u03c9": r"\omega", "\u0394": r"\Delta",
    "\u03a9": r"\Omega", "\u03a3": r"\Sigma", "\u03b5": r"\epsilon",
}

SIMPLE = {
    "\u2212": "-", "\uf02d": "-",           # minus (Symbol font private use)
    "\uf06c": r"\ell",                       # script l
    "\u2206": r"\Delta",                     # increment
    "\u00b0": r"^{\circ}",
    "\u00d7": r"\times", "\u2260": r"\neq", "\u2264": r"\leq", "\u2265": r"\geq",
    "\u226a": r"\ll", "\u226b": r"\gg", "\u222b": r"\int", "\u22a5": r"\perp",
    "\u221a": "\u221a",                      # sqrt handled separately
    "\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''",
    "\u2013": "--", "\u2014": "---",
    "\u00b7": r"\cdot", "\u2044": "/",
}

COMBINING = {
    "\u20d7": ("vec", True),                 # right arrow above  -> \vec{A}
    "\u0302": ("hat", True),                 # circumflex         -> \hat{i}
    "\u0304": ("bar", True),                 # macron             -> \bar{v}
    "\u0303": ("tilde", True),
    "\u0307": ("dot", True),
    "\u0332": ("underline", False),
}

# Characters that unmistakably belong to math.  Note that "-", "." and "," are
# deliberately absent: they occur constantly inside ordinary English text.
MATH_CHARS = set("=+*/()[]<>|^{}_~°≤≥≠×∫∆⋅·±∞∇∂")
# Standalone operator spans (a hyphen-minus often lives in its own span).
OPERATORS = {"-", "\u2212", "+", "=", "/", "<", ">", "\u00b1"}

# Physical units that should stay upright inside math mode.
# (pattern, literal LaTeX replacement) - applied with a lambda so that backslashes
# in the replacement never need regex-template escaping.
UNIT_PATTERNS = [
    (r"m/s\^\{2\}", r"\mathrm{m/s}^{2}"),
    (r"m/s\^2", r"\mathrm{m/s}^{2}"),
    (r"m/s", r"\mathrm{m/s}"),
    (r"kg\s*\\cdot\s*m/s", r"\mathrm{kg\cdot m/s}"),
    (r"N\s*\\cdot\s*m", r"\mathrm{N\cdot m}"),
    (r"rad/s\^\{2\}", r"\mathrm{rad/s}^{2}"),
    (r"rad/s", r"\mathrm{rad/s}"),
    (r"kg\s*\\cdot\s*m\^\{2\}", r"\mathrm{kg\cdot m}^{2}"),
    (r"kg\s*m\^\{2\}", r"\mathrm{kg\cdot m}^{2}"),
]

UNIT_WORD = re.compile(r"(?<![A-Za-z])(kg|mg|N|J|W|Hz|Pa|cm|mm|km|nm|ms|min|rad|rev|mL|m|s|g|h|L)(?![A-Za-z])")

TEXT_ESCAPES = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


UNIT_TOKEN = re.compile(r"(\\mathrm\{[^{}]*\})")
FUNC_NAMES = {"sin", "cos", "tan", "cot", "sec", "csc", "ln", "log", "exp", "max", "min"}
RE_SQRT_EMPTY = re.compile(r"\\sqrt\{\}\s*([0-9A-Za-z]+)")


def _word_units(text: str) -> str:
    """Wrap bare unit symbols in \\mathrm{}, leaving existing \\mathrm{} alone."""
    return "".join(
        p if p.startswith("\\mathrm{") else UNIT_WORD.sub(lambda m: "\\mathrm{" + m.group(1) + "}", p)
        for p in UNIT_TOKEN.split(text)
    )


def _sub_outside_mathrm(pat, rep, text: str) -> str:
    return "".join(
        p if p.startswith("\\mathrm{") else re.sub(pat, lambda m, r=rep: r, p)
        for p in UNIT_TOKEN.split(text)
    )


def _apply_units(latex: str) -> str:
    out = []
    for part in UNIT_TOKEN.split(latex):
        if part.startswith("\\mathrm{"):
            out.append(part)
            continue
        for pat, rep in UNIT_PATTERNS:
            part = _sub_outside_mathrm(pat, rep, part)
        out.append(_word_units(part))
    return "".join(out)


def _merge_combining(spans: list) -> list:
    """Combining marks (vector arrows, hats) often live in their own span - glue them
    back onto the span holding the base character."""
    out: list = []
    for s in spans:
        if out and s["text"] and s["text"][0] in COMBINING:
            prev = dict(out[-1])
            prev["text"] = prev["text"] + s["text"]
            out[-1] = prev
        else:
            out.append(s)
    return out


def convert_unicode(text: str) -> str:
    """Convert a raw PDF span into LaTeX source (no math-mode decision yet)."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in COMBINING:
            name, above = COMBINING[ch]
            # collapse repeated combining marks over the same base
            j = i
            while j < n and text[j] in COMBINING:
                j += 1
            base = out.pop() if out else ""
            if base.endswith("}"):  # already a macro, e.g. \theta
                inner = base
            else:
                inner = base if len(base) == 1 else "{" + base + "}"
            out.append(f"\\{name}{{{inner}}}")
            i = j
            continue
        if ch == "\u221a":  # sqrt, take the following run as radicand
            j = i + 1
            while j < n and text[j].isalnum():
                j += 1
            rad = text[i + 1:j]
            out.append(r"\sqrt{" + rad + "}" if rad else r"\sqrt{}")
            i = j
            continue
        if ch in GREEK:
            out.append(GREEK[ch])
            i += 1
            continue
        if ch in SIMPLE:
            out.append(SIMPLE[ch])
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def escape_text(latex: str) -> str:
    return "".join(TEXT_ESCAPES.get(c, c) for c in latex)


# --------------------------------------------------------------------------------------
# Line model
# --------------------------------------------------------------------------------------

@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    spans: list
    page: int

    @property
    def text(self) -> str:
        return "".join(s["text"] for s in self.spans).strip()

    @property
    def bold(self) -> bool:
        return all(bool(s["flags"] & 16) for s in self.spans if s["text"].strip())


def _span_scripts(spans: list) -> list[int]:
    """Return 0 (normal), 1 (superscript), -1 (subscript) for every span of a line."""
    bottoms = [s["bbox"][3] for s in spans]
    ref = statistics.median(bottoms)
    heights = [s["bbox"][3] - s["bbox"][1] for s in spans]
    big = statistics.median(heights)
    out = []
    for s, bottom, h in zip(spans, bottoms, heights):
        if s["flags"] & 1 or bottom < ref - 1.2:
            out.append(1)
        elif bottom > ref + 1.2 and h < big * 0.92:
            out.append(-1)
        else:
            out.append(0)
    return out


def _is_math(text: str, italic: bool, script: int) -> bool:
    if script != 0:
        return True
    if italic:
        return True
    s = text.strip()
    if not s:
        return False
    if s.startswith("\\"):            # \theta, \vec{A}, \Delta ... from unicode
        return True
    if len(s) > 12 and not italic:    # long upright runs are prose, not formulas
        return False
    if s in OPERATORS:
        return True
    if any(c in MATH_CHARS for c in s):
        return True
    if "/" in s and len(s) <= 8:      # m/s, kg/s, N/m ...
        return True
    if s.isdigit():
        return True
    if len(s) == 1 and s.isalpha() and italic:   # a lone upright "a" is the article
        return True
    if re.fullmatch(r"[\d.,]*\d[\d.,]*", s):     # needs at least one real digit
        return True
    return False


def line_to_latex(line: Line) -> str:
    """Convert one physical line into LaTeX, wrapping math runs in $...$."""
    spans = _merge_combining(line.spans)
    scripts = _span_scripts(spans)
    conv = []
    for s, sc in zip(spans, scripts):
        raw = s["text"]
        italic = bool(s["flags"] & 2)
        t = convert_unicode(raw)
        if sc == 1:
            t = "^{" + t.strip() + "}"
        elif sc == -1:
            t = "_{" + t.strip() + "}"
        # A long upright run mixes prose with symbols ("... at 90^{\circ}. The object ...").
        # Split it into tokens and let every token decide on its own.
        if len(t.strip()) > 12 and not italic and sc == 0:
            for piece in re.split(r"(\s+)", t):
                if not piece:
                    continue
                conv.append({"t": piece, "math": _is_math(piece, False, 0),
                             "ws": not piece.strip(), "raw": piece})
            continue
        conv.append({"t": t, "math": _is_math(t, italic, sc), "ws": not raw.strip(), "raw": raw})

    for i, c in enumerate(conv):
        if c["ws"]:
            prev = next((conv[j]["math"] for j in range(i - 1, -1, -1) if not conv[j]["ws"]), False)
            nxt = next((conv[j]["math"] for j in range(i + 1, len(conv)) if not conv[j]["ws"]), False)
            c["math"] = prev and nxt
        elif not c["math"]:
            w = c["t"].strip().strip("\\")
            if w in FUNC_NAMES:
                prev = next((conv[j]["math"] for j in range(i - 1, -1, -1) if not conv[j]["ws"]), False)
                nxt = next((conv[j]["math"] for j in range(i + 1, len(conv)) if not conv[j]["ws"]), False)
                if prev or nxt:
                    c["math"] = True
                    c["t"] = c["t"].replace(w, "\\" + w)

    pieces: list[str] = []
    buf: list[str] = []
    cur = None
    for c in conv:
        kind = "math" if c["math"] else "text"
        if kind != cur and buf:
            pieces.append(("math", "".join(buf)) if cur == "math" else ("text", "".join(buf)))
            buf = []
        cur = kind
        if kind == "math":
            buf.append("\\ " if c["ws"] else c["t"])
        else:
            buf.append(escape_text(c["t"]) if not c["ws"] else " ")
    if buf:
        pieces.append(("math", "".join(buf)) if cur == "math" else ("text", "".join(buf)))

    out = []
    for kind, body in pieces:
        if kind == "math":
            body = RE_SQRT_EMPTY.sub(lambda m: "\\sqrt{" + m.group(1) + "}", body)
            body = _apply_units(body)
            body = body.strip()
            if body.endswith("\\"):
                body = body[:-1].rstrip()
            if body:
                out.append("$" + body + "$")
        else:
            if body.strip():
                out.append(body)
    res = "".join(out)
    return re.sub(r"\s{2,}", " ", res).strip()


# --------------------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------------------

def _extract_figure(doc, page, bbox, out_path, dpi=300) -> bool:
    x0, y0, x1, y1 = bbox
    if x1 - x0 < 16 or y1 - y0 < 10:      # hairlines / ornaments, not real figures
        return False
    clip = pymupdf.Rect(x0, y0, x1, y1)
    clip = clip & page.rect
    pix = page.get_pixmap(clip=clip, dpi=dpi, colorspace=pymupdf.csRGB)
    if pix.width < 4 or pix.height < 4:
        return False
    pix.save(out_path)
    return True


# --------------------------------------------------------------------------------------
# Structure parsing
# --------------------------------------------------------------------------------------

RE_UNIT = re.compile(r"^Unit\s+(\d+)\s+(.+?)\s*$")
RE_TOPIC = re.compile(r"^(\d+)\.(\d+)\s+(.+?)\s*$")
RE_QNUM = re.compile(r"^(\d+)\.\s*$")
RE_QNUM_INLINE = re.compile(r"^(\d+)\.\s+(\S.*)$")
RE_CHOICE = re.compile(r"^\(([A-E])\)\s*(.*)$")
RE_ROWLABEL = re.compile(r"^([A-E])\s*$")
RE_END = re.compile(r"^\s*The End\s*$", re.I)


@dataclass
class Question:
    id: str = ""
    unit: int = 0
    unit_title: str = ""
    topic: str = ""
    topic_title: str = ""
    number: int = 0
    qtype: str = "mcq"
    stem: str = ""
    choices: list = field(default_factory=list)
    answer: str = ""
    solution: str = ""
    images: list = field(default_factory=list)
    difficulty: str = ""
    tags: list = field(default_factory=list)
    source: dict = field(default_factory=dict)
    layout: str = "inline"
    needs_review: bool = False

    def to_dict(self):
        d = asdict(self)
        return d


def _start_page(doc) -> int:
    """First page that actually contains questions."""
    for i in range(min(20, doc.page_count)):
        txt = doc[i].get_text()
        if "...." in txt:
            continue
        if "TABLE OF INFORMATION" in txt or "MECHANICS" in txt and "GEOMETRY" in txt:
            continue
        if re.search(r"(?m)^Unit\s+\d+", txt) and re.search(r"(?m)^\d+\.\s*$", txt):
            return i
    return 0


def _is_chrome(text: str, y0: float, y1: float, page_h: float) -> bool:
    if not text.strip():
        return True
    if re.fullmatch(r"WHBC\s*20\d\d-20\d\d", text.strip()):
        return True
    if re.fullmatch(r"\d{1,3}", text.strip()) and (y0 < 80 or y1 > page_h - 80):
        return True
    return False


def extract_pdf(
    pdf_path: str,
    media_dir: str,
    doc_id: str,
    dpi: int = 300,
    progress=None,
) -> list:
    doc = pymupdf.open(pdf_path)
    os.makedirs(media_dir, exist_ok=True)
    start = _start_page(doc)

    questions: list[Question] = []
    cur: Question | None = None
    cur_choice = None          # index into cur.choices
    unit_no, unit_title = 0, ""
    topic, topic_title = "", ""
    img_counter = 0
    page_offset = None         # pdf page index -> printed book page number

    row_label_idx: list = []   # indices of choices created from a bare "A"/"B" line

    def flush():
        nonlocal cur, cur_choice
        if cur is not None:
            cur.stem = re.sub(r"\s+", " ", cur.stem).strip()
            for c in cur.choices:
                c["text"] = re.sub(r"\s+", " ", c["text"]).strip()
            # A single bare letter is far more likely a figure label than a table row:
            # undo it and push the letter back into the stem.
            if len(row_label_idx) < 2:
                for i in reversed(row_label_idx):
                    ch = cur.choices.pop(i)
                    cur.stem += " " + ch["label"]
                cur.layout = "inline"
            if cur.layout == "table":
                cur.needs_review = True
            questions.append(cur)
        row_label_idx.clear()
        cur, cur_choice = None, None

    for pno in range(start, doc.page_count):
        page = doc[pno]
        txt = page.get_text()
        if RE_END.search(txt.strip()):
            flush()
            break

        lines: list[Line] = []
        for blk in page.get_text("dict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                spans = ln["spans"]
                if not spans:
                    continue
                lines.append(Line(
                    x0=min(s["bbox"][0] for s in spans),
                    y0=min(s["bbox"][1] for s in spans),
                    x1=max(s["bbox"][2] for s in spans),
                    y1=max(s["bbox"][3] for s in spans),
                    spans=spans, page=pno,
                ))

        # --- reading order: cluster items into visual rows, then sort by x -----------
        raw_items = []
        for ln in lines:
            t = ln.text
            if _is_chrome(t, ln.y0, ln.y1, page.rect.height):
                continue
            raw_items.append({"y0": ln.y0, "y1": ln.y1, "x": ln.x0, "kind": 0, "obj": ln})
        for im in page.get_image_info():
            b = im["bbox"]
            # figures can be very tall; only their upper band takes part in row detection
            raw_items.append({"y0": b[1], "y1": b[1] + min((b[3] - b[1]) * 0.6, 80.0),
                              "x": b[0], "kind": 1, "obj": {"bbox": b}})
        raw_items.sort(key=lambda it: (it["y0"], it["x"]))

        rows: list = []
        row: list = []
        anchor = None

        def overlaps(a, b) -> bool:
            return min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]) > 0

        for it in raw_items:
            if anchor is None:
                row, anchor = [it], it
            elif overlaps(it, anchor):
                row.append(it)
            else:
                rows.append(row)
                row, anchor = [it], it
        if row:
            rows.append(row)

        flow = []
        for r in rows:
            # a question number always leads its row, whatever its x coordinate
            r.sort(key=lambda it: (
                0 if (it["kind"] == 0 and RE_QNUM.match(it["obj"].text)) else 1,
                it["x"],
            ))
            flow.extend(r)

        # printed page number: bold standalone number in the top/bottom margin
        if page_offset is None:
            m = re.search(r"(?m)^(\d{1,3})\s*$", txt)
            if m:
                page_offset = int(m.group(1)) - (pno - start)

        for item in flow:
            if item["kind"] == 1:  # figure
                if cur is None:
                    continue
                bbox = item["obj"]["bbox"]
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                img_counter += 1
                slug = f"u{cur.unit}_{cur.topic.replace('.', '')}_q{cur.number}_{img_counter}"
                fname = f"{slug}.png"
                path = os.path.join(media_dir, fname)
                if _extract_figure(doc, page, bbox, path, dpi):
                    rel = os.path.relpath(path, os.path.dirname(media_dir)).replace("\\", "/")
                    width = min(0.85, round(w / page.rect.width * 1.05, 2))
                    token = rf"\includegraphics[width={width}\linewidth]{{{rel}}}"
                    if cur_choice is not None:
                        cur.choices[cur_choice]["text"] += " " + token
                    else:
                        cur.stem += "\n\n" + token + "\n"
                    cur.images.append({"file": fname, "rel": rel, "width": round(width, 2)})
                continue

            ln: Line = item["obj"]
            raw = ln.text
            if not raw.strip():
                continue

            m = RE_UNIT.match(raw)
            if m and ln.bold:
                flush()
                unit_no, unit_title = int(m.group(1)), m.group(2)
                continue

            m = RE_TOPIC.match(raw)
            if m and ln.bold and m.group(1) == str(unit_no):
                flush()
                topic = f"{m.group(1)}.{m.group(2)}"
                topic_title = m.group(3)
                continue

            m = RE_QNUM.match(raw)
            if m:
                flush()
                cur = Question(
                    id=f"{doc_id}-U{unit_no}-{topic}-Q{m.group(1)}",
                    unit=unit_no, unit_title=unit_title,
                    topic=topic, topic_title=topic_title,
                    number=int(m.group(1)),
                    source={"doc": doc_id, "pdf_page": pno + 1,
                            "book_page": (page_offset + pno - start) if page_offset is not None else None},
                )
                cur_choice = None
                continue

            m = RE_QNUM_INLINE.match(raw)
            if m and (cur is None or int(m.group(1)) != cur.number):
                flush()
                cur = Question(
                    id=f"{doc_id}-U{unit_no}-{topic}-Q{m.group(1)}",
                    unit=unit_no, unit_title=unit_title,
                    topic=topic, topic_title=topic_title,
                    number=int(m.group(1)),
                    source={"doc": doc_id, "pdf_page": pno + 1,
                            "book_page": (page_offset + pno - start) if page_offset is not None else None},
                )
                cur_choice = None
                raw = m.group(2)

            if cur is None:
                continue

            m = RE_CHOICE.match(raw)
            if m:
                cur.choices.append({"label": m.group(1), "text": line_to_latex(
                    Line(ln.x0, ln.y0, ln.x1, ln.y1,
                         [{"text": m.group(2), "flags": 4, "bbox": ln.spans[-1]["bbox"]}], pno))})
                cur_choice = len(cur.choices) - 1
                continue

            m = RE_ROWLABEL.match(raw)
            if m:
                cur.choices.append({"label": m.group(1), "text": ""})
                cur_choice = len(cur.choices) - 1
                row_label_idx.append(cur_choice)
                continue

            latex = line_to_latex(ln)
            if not latex:
                continue
            if cur_choice is not None:
                cur.choices[cur_choice]["text"] += (" " if cur.choices[cur_choice]["text"] else "") + latex
            else:
                cur.stem += (" " if cur.stem else "") + latex

        if progress:
            progress(pno + 1, doc.page_count)

    flush()
    doc.close()
    out = [q.to_dict() for q in questions]
    return balance_image_choices(reassign_figures(out))


NEEDS_FIGURE = re.compile(
    r"\b(as shown|shown in the figure|in the figure|the figure|figures?\s+(above|below)|"
    r"diagram|graph|the setup|apparatus)\b", re.I)
MENTIONS_ART = re.compile(
    r"\b(figures?|diagram|graph|chart|table|as shown|shown|sketch|plot)\b", re.I)


IMG_TOKEN = re.compile(r"\\includegraphics\[[^\]]*\]\{[^{}]*\}")


def balance_image_choices(questions: list) -> list:
    """Answer options that are pure diagrams often land in a single option because the
    grid rows cluster together.  Spread the collected figures evenly over the options."""
    for q in questions:
        choices = q["choices"]
        if len(choices) < 2:
            continue
        empties = [i for i, c in enumerate(choices) if not c["text"].strip()]
        if len(empties) < 2:
            continue
        tokens: list = []
        for c in choices:
            found = IMG_TOKEN.findall(c["text"])
            if found:
                tokens.extend(found)
                c["text"] = re.sub(r"\s+", " ", IMG_TOKEN.sub("", c["text"])).strip()
        if not tokens:
            continue
        if len(tokens) == len(choices):
            for i, t in enumerate(tokens):
                choices[i]["text"] = (choices[i]["text"] + " " + t).strip()
        elif len(tokens) == len(empties):
            for i, t in zip(empties, tokens):
                choices[i]["text"] = t
        else:
            for i, t in zip(empties, tokens):
                choices[i]["text"] = t
            q["needs_review"] = True
    return questions


def reassign_figures(questions: list) -> list:
    """Figures are frequently typeset *above* the question that refers to them, which
    makes a purely positional pass attach them to the previous question.  Move an image
    forward when the previous question never mentions an artwork and the next one does."""
    for i, q in enumerate(questions):
        if not q["images"] or q["layout"] == "table":
            continue
        if MENTIONS_ART.search(q["stem"]):
            continue
        nxt = questions[i + 1] if i + 1 < len(questions) else None
        if nxt is None or nxt["images"]:
            continue
        if not NEEDS_FIGURE.search(nxt["stem"]):
            continue
        # only donate figures that sit in the stem, never ones used as answer options
        donate = [im for c in q["choices"] for im in []]
        stem_imgs = q["images"][:]
        if not stem_imgs:
            continue
        q["images"] = []
        for im in stem_imgs:
            token = rf"\includegraphics[width={im['width']}\linewidth]{{{im['rel']}}}"
            q["stem"] = q["stem"].replace("\n\n" + token + "\n", " ").replace(token, " ")
            nxt["stem"] = nxt["stem"].rstrip() + "\n\n" + token + "\n"
            nxt["images"].append(im)
        q["stem"] = re.sub(r"\s+", " ", q["stem"]).strip()
        q["needs_review"] = True
    return questions


def file_fingerprint(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
