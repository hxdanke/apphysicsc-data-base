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
SYMBOL_MACRO = re.compile(r"\\([A-Za-z]+)")
# Every symbol macro convert_unicode() can emit.  A run holding one is a formula
# even when nothing else about it looks mathematical.
MATHS_MACROS = frozenset({
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu",
    "pi", "rho", "sigma", "tau", "varphi", "phi", "omega", "Delta", "Omega",
    "Sigma", "ell", "circ", "degree", "times", "neq", "leq", "geq", "ll",
    "gg", "int", "perp", "cdot", "vec", "hat", "bar", "tilde", "dot",
    "sqrt", "infty", "partial", "nabla", "approx", "propto", "pm",
})
FUNC_NAMES = {"sin", "cos", "tan", "cot", "sec", "csc", "ln", "log", "exp", "max", "min"}
# Connecting words that sit between two formulas ("... m/s and v_y = ...").  They
# are italic-free prose, but the surrounding maths would otherwise swallow them.
PROSE_WORDS = {"and", "or", "where", "if", "then", "when", "at", "is", "the", "with",
               "for", "from", "to", "in", "of", "a", "an", "given", "by", "so", "as",
               "are", "was", "be", "that", "which", "while", "than", "between"}
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


# Units written flush against a number ("2s", "5\u03bcm") lose the separating
# space because the PDF stores the gap as kerning, not as a real space.  Every
# real unit is normalised to ``\mathrm{...}`` by ``_word_units``, so the spacing
# is handled by the ``\mathrm`` rules below -- a bare letter after a digit is
# always an implicit product (``5t``), never a unit.
RE_NUM_MATHML = re.compile(r"(?<=[0-9])(?=\\mathrm\{)")
RE_MATHML_NUM = re.compile(r"(\\mathrm\{[^{}]*\})(?=[0-9(])")
# ``(4t - 5)\mathrm{m/s}`` / ``6\mathrm{m/s}`` -- a value immediately followed by a
# unit needs the thin space the printed book shows.
RE_CLOSE_MATHML = re.compile(r"(?<=[)\]])(?=\\mathrm\{)")
# a bracket opening right onto a unit is never a value+unit pair, leave it alone


def _space_num_unit(latex: str) -> str:
    """Thin space between a number and the unit that follows (or precedes) it.

    Only real units need this, and ``_word_units`` has already turned every one
    of them into ``\\mathrm{...}`` by the time we get here.  We must *not* add a
    space before a bare letter: in this book ``5t``, ``2F_0``, ``3R`` ... are
    implicit products (the letter is a physics quantity), and an explicit ``\\ ``
    there renders as ``5 t`` -- visibly wrong.
    """
    joined = RE_NUM_MATHML.sub(r"\\ ", latex)
    joined = RE_CLOSE_MATHML.sub(r"\\ ", joined)
    joined = RE_MATHML_NUM.sub(r"\1\\ ", joined)
    # an ordinary space in maths mode renders as nothing
    return re.sub(r"(?<=[0-9)\]])\s+(?=\\mathrm\{)", r"\\ ", joined)


# ``\Deltat`` / ``\alphar`` -- a Greek macro with the next letter glued on by the
# kerning.  The engine would treat the whole run as one undefined command.
_GLUE_ROOTS = ("varepsilon", "vartheta", "varphi", "Delta", "Omega", "Theta",
               "Lambda", "Sigma", "Gamma", "alpha", "beta", "gamma", "delta",
               "epsilon", "theta", "lambda", "omega", "sigma", "phi", "varphi",
               "kappa", "mu", "pi", "rho", "tau", "ell", "psi")
# Any letter may follow -- enumerating the likely ones left "\pif_{0}" intact and
# the compiler read it as one undefined command (Unit 7.3 Q9).
RE_GLUED = re.compile(
    r"\\(" + "|".join(sorted(set(_GLUE_ROOTS), key=len, reverse=True))
    + r")([A-Za-z])")


def _split_glued_macros(latex: str) -> str:
    return RE_GLUED.sub(lambda m: "\\" + m.group(1) + " " + m.group(2), latex)


def _apply_units(latex: str) -> str:
    out = []
    for part in UNIT_TOKEN.split(latex):
        if part.startswith("\\mathrm{"):
            out.append(part)
            continue
        for pat, rep in UNIT_PATTERNS:
            part = _sub_outside_mathrm(pat, rep, part)
        out.append(_word_units(part))
    return _space_num_unit("".join(out))


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


_MACRO_RUN = re.compile(r"\\(?:[A-Za-z]+|.)")


def escape_text(latex: str) -> str:
    """Escape LaTeX specials in prose, but leave real macros alone.

    ``convert_unicode`` has already turned the Greek and the symbols of a span
    into macros.  Escaping their backslash too would print "2\\pi" as the words
    "2\\textbackslash{}pi", so anything starting with a backslash passes through.
    """
    out: list[str] = []
    i, n = 0, len(latex)
    while i < n:
        c = latex[i]
        if c == "\\":
            m = _MACRO_RUN.match(latex, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
        out.append(TEXT_ESCAPES.get(c, c))
        i += 1
    return "".join(out)


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
    # filled in by _mark_fractions(): this line carries a stacked fraction
    frac_num: str = ""      # numerator, sitting on the line above
    den_x1: float = 0.0     # right edge of the numerator -> splits the denominator
    skip: bool = False      # the numerator line itself is consumed by the fraction
    # what the PDF actually says on this line, before any repair.  Kept so an
    # audit can compare every emitted question against the printed original.
    raw: str = ""
    # keys of every printed row this line was built from -- its own row plus the
    # rows of any fraction it swallowed.  Counting each row once keeps the audit
    # from crediting the page with the numerator twice.
    srcs: tuple = ()

    @property
    def text(self) -> str:
        return "".join(s["text"] for s in self.spans).strip()

    @property
    def bold(self) -> bool:
        return all(bool(s["flags"] & 16) for s in self.spans if s["text"].strip())


# Word-to-PDF converters leave the "superscript" font bit set on rows that are
# printed at full size and on the normal baseline (page 79 alone has five of
# them: "at t = 2. Multiply the result by \Delta t").  Believing the bit turns
# whole clauses into ^{...}.  The layout has the last word: only trust it when
# the glyph is actually set smaller than the row it belongs to.
SCRIPT_SIZE_RATIO = 0.92


# How far a glyph has to move off the baseline before it counts as raised.
SCRIPT_SHIFT = 0.8


def _span_size(s: dict) -> float:
    return float(s.get("size") or (s["bbox"][3] - s["bbox"][1]) or 0.0)


def _baseline_of(spans: list) -> tuple[float, float]:
    """(baseline, full size) of one run of glyphs.

    The baseline is voted for by the full-size glyphs only, so a row whose
    scripts outnumber its letters ("e^{-\\theta_{f}/k}") cannot vote the whole
    row down onto the scripts.
    """
    plain = [s for s in spans if s["text"].strip()]
    if not plain:
        return statistics.median([s["bbox"][3] for s in spans]), 0.0
    sizes = [_span_size(s) for s in plain]
    top = max(sizes)
    votes: dict[float, int] = {}
    for s, sz in zip(plain, sizes):
        if sz < top * SCRIPT_SIZE_RATIO:
            continue
        k = round(s["bbox"][3], 1)
        votes[k] = votes.get(k, 0) + 1
    ref = max(votes, key=lambda k: votes[k]) if votes else top
    return ref, top


def _script_items(spans: list) -> list:
    """Sort one run of spans into ordinary glyphs and the scripts rising off them.

    Returns ``[("base", [span]), ...]`` mixed with ``("^"/"_", items)``, always
    in reading order.  A script is recognised by its *size* -- nothing on the
    printed page is ever raised at full height -- and then by which side of the
    baseline it sits.  Each script run is laid out again against its own
    baseline, so a nested exponent nests instead of coming out as the chain
    ``$^{-}^{\\theta}^{f}^{/}^{k}$`` that page 105 used to produce.

    Word-to-PDF converters also leave the "superscript" font bit set on rows
    printed at full size (page 79: "at t = 2. Multiply the result by ..."),
    which used to turn whole clauses into superscripts.  Size is the honest
    witness here, so the bit is not consulted at all.
    """
    ref, top = _baseline_of(spans)
    if not top:
        return [("base", [s]) for s in spans]

    def direction(s: dict) -> int:
        if not s["text"].strip():                      # a kern never moves
            return 0
        if _span_size(s) >= top * SCRIPT_SIZE_RATIO:
            return 0
        bottom = s["bbox"][3]
        if bottom < ref - SCRIPT_SHIFT:
            return 1
        if bottom > ref + SCRIPT_SHIFT:
            return -1
        return 0

    out: list = []
    i = 0
    while i < len(spans):
        d = direction(spans[i])
        if d == 0:
            out.append(("base", [spans[i]]))
            i += 1
            continue
        j = i
        run = []
        while j < len(spans) and direction(spans[j]) == d:
            run.append(spans[j])
            j += 1
        out.append(("^" if d > 0 else "_", _script_items(run)))
        i = j
    return out


def _render_scripts(items: list) -> str:
    """LaTeX body of one laid-out run, scripts already folded in."""
    out: list[str] = []
    for kind, payload in items:
        if kind == "base":
            for s in _merge_combining(payload):
                out.append(_frac_conv(s["text"]).strip())
        else:
            out.append(kind + "{" + _render_scripts(payload).strip() + "}")
    return "".join(out)


RE_LABEL_SPAN = re.compile(r"^\s*(\([A-E]\)|[A-E])\s*$")


def _mark_fractions(lines: list) -> None:
    """Join stacked fractions back together.

    A fraction is typeset with the numerator on a line of its own, raised above
    the line that starts with the denominator; the bar itself is nowhere to be
    found in the drawing list, so the two lines only reveal themselves by
    overlapping vertically while the upper one is a very short token.
    """
    for a in lines:
        t = a.text.strip()
        if not t or len(t) > 4:
            continue
        if RE_CHOICE.match(t) or RE_QNUM.match(t) or RE_ROWLABEL.match(t):
            continue
        if not re.fullmatch(r"[0-9A-Za-z]+|\\\w+", t):
            continue
        best = None
        for b in lines:
            if b is a or b.y0 <= a.y0 or a.y1 <= b.y0:
                continue
            if b.y0 - a.y0 > 9:            # too far below to be stacked
                continue
            if b.x1 < a.x0 or b.x0 > a.x1:  # no horizontal overlap
                continue
            if best is None or (b.y0 - a.y0) < (best.y0 - a.y0):
                best = b
        if best is None or best.frac_num:
            continue
        best.frac_num = t
        best.den_x1 = a.x1 + 0.3
        a.skip = True


def _split_fraction(line: Line) -> tuple[list, list, list]:
    """(label spans, denominator spans, remaining spans) for a stacked fraction."""
    label, den, rest = [], [], []
    started = False
    for s in line.spans:
        if not started and RE_LABEL_SPAN.match(s["text"]):
            label.append(s)
            continue
        started = True
        if s["bbox"][0] < line.den_x1:
            den.append(s)
        else:
            rest.append(s)
    if not den and rest:
        den.append(rest.pop(0))
    return label, den, rest


def _latex_of_spans(spans: list, page: int, fallback: Line) -> str:
    if not spans:
        return ""
    return line_to_latex(Line(min(s["bbox"][0] for s in spans),
                             min(s["bbox"][1] for s in spans),
                             max(s["bbox"][2] for s in spans),
                             max(s["bbox"][3] for s in spans),
                             spans, page))


# Operators whose limits are printed above *and* below the sign.
BIG_OPERATORS = "\u222b\u222c\u222e\u2211\u220f\u2210"
# How far to the left of its limit the sign itself may sit.
LIMIT_HUG = 14.0


def _looks_like_limit(host: dict, orphan: dict) -> bool:
    """True when ``orphan`` is a limit of a large operator printed in ``host``.

    An integral is drawn with its bounds tucked above and below the sign, far
    enough out that pymupdf files each of them as a line of its own -- and they
    are then printed as "\\int \\omega(t) 3 dt ... 1" (Unit 5.1 Q2).  Only a
    script-size glyph hugging such a sign qualifies, so "4 rad/s" + a raised "2"
    and the numerator of a stacked fraction are left alone.
    """
    live = [s for s in host["spans"] if s["text"].strip()]
    odds = [s for s in orphan["spans"] if s["text"].strip()]
    if len(odds) != 1 or len(odds[0]["text"].strip()) > 4 or not live:
        return False
    top = max(float(s["size"]) for s in live)
    small = float(odds[0]["size"])
    if top <= 0 or small >= top * 0.85:
        return False
    b = odds[0]["bbox"]
    band = (min(s["bbox"][1] for s in live), max(s["bbox"][3] for s in live))
    cover = min(band[1], b[3]) - max(band[0], b[1])
    if cover <= 0 or cover < (b[3] - b[1]) * 0.5:
        return False
    return any(s["text"].strip() in BIG_OPERATORS and abs(s["bbox"][2] - b[0]) <= LIMIT_HUG
               for s in live)


def _absorb_limits(layout: dict) -> None:
    """Fold the limits of a large operator back into the line holding the sign."""
    rows = [ln for blk in layout["blocks"] if blk["type"] == 0 for ln in blk["lines"]]
    host: dict | None = None
    for ln in rows:
        if host is not None and ln["spans"] and _looks_like_limit(host, ln):
            merged = sorted(host["spans"] + ln["spans"], key=lambda s: s["bbox"][0])
            host["spans"].clear()
            host["spans"].extend(merged)
            ln["spans"].clear()
            continue
        host = ln


# --------------------------------------------------------------------------- #
# geometry-driven reconstruction of stacked fractions / radicals
# --------------------------------------------------------------------------- #

def _frac_conv(text: str) -> str:
    """Map one raw PDF string to the LaTeX used *inside* maths."""
    return _split_glued_macros(convert_unicode(text))


def reconstruct_lines(page) -> list[Line]:
    """Rebuild a page's lines, folding stacked fractions and radicals back in.

    The extractor walks PDF spans, which loses the vertical structure of every
    stacked fraction.  This pass locates the *drawn* fraction rules, rebuilds
    each fraction / radical from them (see :mod:`server.fractions`) and returns
    the page's pymupdf lines with the fraction spans replaced by a single span
    holding its ready-made ``\\frac{}{}``.  Line grouping is otherwise left
    untouched, so question, choice and heading detection keep working.
    """
    from .fractions import (RADICAL_GLYPHS, Builder, Span as FSpan,
                            collect_bars, node_latex)

    layout = page.get_text("dict")
    _absorb_limits(layout)
    fspans: list[FSpan] = []
    orig_of: dict[int, dict] = {}          # id(FSpan) -> the pymupdf span dict
    line_of: dict[int, list] = {}          # id(FSpan) -> the pymupdf line it came from
    base = page.number << 20               # keeps row keys unique across the book
    key_of: dict[int, int] = {}            # id(pymupdf line) -> its row key
    idx = 0
    for blk in layout["blocks"]:
        if blk["type"] != 0:
            continue
        for ln in blk["lines"]:
            key_of[id(ln)] = base + idx
            idx += 1
            for s in ln["spans"]:
                if s["text"]:
                    fs = FSpan(s["bbox"][0], s["bbox"][1], s["bbox"][2],
                               s["bbox"][3], s["text"], s["flags"], s["size"])
                    fspans.append(fs)
                    orig_of[id(fs)] = s
                    line_of[id(fs)] = ln
    row_text = {k: "" for k in key_of.values()}
    if not fspans:
        return []

    nodes = Builder(fspans, collect_bars(page)).run()

    # A span swallowed by a fraction / radical is owned by it.  The piece itself
    # is written out once, at the position of its left-most span, so "(C) 2 <x>"
    # keeps its reading order.
    pieces: dict[int, dict] = {}           # marker -> {latex, x0, x1}
    owner: dict[int, int] = {}             # id(pymupdf span) -> marker
    rewrite: dict[int, str] = {}           # id(pymupdf span) -> text minus its radical
    piece_rows: dict[int, list] = {}        # marker -> row keys it swallowed
    insert_at: set[int] = set()            # the span that carries the piece
    for n in nodes:
        if n.kind == "atom":
            continue
        marker = id(n)
        # A stacked piece is drawn across several rows, so its box has to cover
        # all of them.  Borrowing the height of the one line it happens to be
        # written on puts a short fraction in a visual row of its own and lets
        # the "(A) [1/2](x) (B) [2/3](x)" grid fall apart (see Unit 6.6 Q2).
        # The numerator and the denominator are separate rows, so two spans can
        # meet inside the finished piece and glue a macro to a letter
        # ("\frac{a_0}{2\pif_0}").  Each piece is therefore re-checked as a whole.
        pieces[marker] = {"latex": _split_glued_macros(node_latex(n, _frac_conv)),
                          "x0": n.x0, "x1": n.x1, "y0": n.y0, "y1": n.y1}
        # every span the piece swallowed, including the "v" of a radical that
        # sits *inside* it -- a stray radical would otherwise be printed again
        # on its own and come out as an empty "\sqrt{}"
        owned_spans: list = []
        glyph_spans: list = []
        stack = [n]
        while stack:
            cur = stack.pop()
            if cur.kind == "atom":
                owned_spans.extend(cur.spans)
                continue
            if cur.glyph is not None:
                glyph_spans.append(cur.glyph)
            stack.extend(cur.body + cur.num + cur.den)
        # The "v" may share its span with other characters -- "\cos(\sqrt{x}t)"
        # arrives as the single span " (\u221a".  Drop only the sign and keep
        # the rest of that span in the line.
        for fs in glyph_spans:
            orig = orig_of.get(id(fs))
            if orig is None:
                continue
            stripped = "".join(ch for ch in fs.text if ch not in RADICAL_GLYPHS)
            if stripped.strip():
                rewrite[id(orig)] = stripped
            else:
                owner[id(orig)] = marker
        for fs in owned_spans:
            orig = orig_of.get(id(fs))
            if orig is not None:
                owner[id(orig)] = marker
        # Each row of a stack is its own PDF line, and only one of them ends up
        # carrying the finished piece.  Remember the wording of every row so an
        # audit comparing a question against the printed page is not misled into
        # thinking the numerator / denominator were invented.
        rows = []
        for fs in owned_spans + glyph_spans:
            ln = line_of.get(id(fs))
            if ln is not None and not any(ln is r for r in rows):
                rows.append(ln)
                row_text[key_of[id(ln)]] = "".join(s["text"] for s in ln["spans"])
        piece_rows[marker] = [key_of[id(r)] for r in rows]
        if owned_spans:
            left = min(owned_spans, key=lambda s: s.x0)
            orig = orig_of.get(id(left))
            if orig is not None:
                insert_at.add(id(orig))

    lines: list[Line] = []
    emitted: set[int] = set()
    for blk in layout["blocks"]:
        if blk["type"] != 0:
            continue
        for ln in blk["lines"]:
            new_spans = []
            srcs: list[int] = []
            key = key_of[id(ln)]
            row_text[key] = "".join(s["text"] for s in ln["spans"])
            for s in ln["spans"]:
                if not s["text"]:
                    continue
                marker = owner.get(id(s))
                if marker is None:
                    if id(s) in rewrite:
                        s = dict(s, text=rewrite[id(s)])
                    new_spans.append(s)
                    continue
                if id(s) not in insert_at or marker in emitted:
                    continue               # another part of a piece already written
                emitted.add(marker)
                srcs.extend(piece_rows.get(marker, ()))
                pc = pieces[marker]
                new_spans.append({"text": pc["latex"], "flags": 0, "is_latex": True,
                                  "bbox": (pc["x0"], pc["y0"], pc["x1"], pc["y1"])})
            if not new_spans:
                continue
            ROW_TEXT.update({k: row_text[k] for k in row_text})
            lines.append(Line(
                x0=min(sp["bbox"][0] for sp in new_spans),
                y0=min(sp["bbox"][1] for sp in new_spans),
                x1=max(sp["bbox"][2] for sp in new_spans),
                y1=max(sp["bbox"][3] for sp in new_spans),
                spans=new_spans, page=0,
                raw=row_text[key],
                srcs=tuple(dict.fromkeys([key] + srcs)),
            ))
    return lines


def _attach_fraction(frac: str, latex: str) -> str:
    """Put `\frac{..}{..}` inside the maths run it belongs to."""
    if not frac:
        return latex
    if latex.startswith("$"):
        return "$" + frac + "\\ " + latex[1:]
    return f"${frac}$ {latex}"


def _prose_word(c: dict) -> bool:
    """True for a short English connector that must not be absorbed into maths."""
    return (not c["math"]) and c["t"].strip().lower().strip(".,;:") in PROSE_WORDS


_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# Words the same book prints upright somewhere.  The publisher sets a key term
# ("below", "linear", "changes") in italics, which looks exactly like a physics
# quantity; anything the prose also writes upright is English and is set with
# \textit{} instead of becoming a product of italic variables.
VOCABULARY: set[str] = set()


def _learn_vocabulary(doc) -> None:
    """Collect the upright words of one document before converting it."""
    vocab: set[str] = set()
    for page in doc:
        for blk in page.get_text("dict")["blocks"]:
            if blk["type"]:
                continue
            for ln in blk["lines"]:
                for s in ln["spans"]:
                    if s["flags"] & 2 or not s["text"]:
                        continue
                    vocab.update(w.lower() for w in _WORD_RE.findall(s["text"]))
    VOCABULARY.clear()
    VOCABULARY.update(vocab)


def _is_english(text: str) -> bool:
    """True when every word of an italic run is in the document's prose.

    Parentheses are ignored rather than treated as part of a word, so the
    "scenario(s)" and "(have)" of Unit 7.1 Q4 are read as English too.
    """
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 3]
    return bool(words) and all(w in VOCABULARY for w in words)


def _mixed_upright(text: str) -> bool:
    """True when an upright run carries both formulas and ordinary words.

    The page prints them in one span all the time -- "to the left with speed
    /2. Is this ", "varies as a is in m/s" -- and taking the run as maths
    typesets the English as an italic product of letters.  The whole run is a
    formula only when every word in it is one.
    """
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if len(words) < 2:
        return False
    return len({_is_math(w, False, 0) for w in words}) > 1


def _is_math(text: str, italic: bool, script: int) -> bool:
    if script != 0:
        return True
    if italic:
        # A lower-case connector is English typography, not a formula.  A
        # capital is never the article "a" -- in "\lambda = A - Bx" both A and
        # B print italic and both are quantities (Unit 2.1 Q5).
        w = text.strip()
        if w.lower().strip(".,;:") in PROSE_WORDS and (len(w) > 1 or w.islower()):
            return False
        # a key word emphasised italics-first: still English
        if _is_english(text):
            return False
        return True
    s = text.strip()
    if not s:
        return False
    if s.startswith("\\"):            # \theta, \vec{A}, \Delta ... from unicode
        return True
    if len(s) > 12 and not italic:    # long upright runs are prose, not formulas
        return False
    # ``m/s and`` -- a unit glued to an English connector by the kerning: the
    # connector wins, otherwise it is rendered as maths and "and" turns italic.
    # Checked before the symbol test because "/" is a maths character.
    if re.search(r"(?<![A-Za-z])(?:and|or|where|the|is|at|to|of|by|for|from)(?![A-Za-z])", s):
        return False
    if s in OPERATORS:
        return True
    if any(c in MATH_CHARS for c in s):
        # "(s)" is the printed plural, not a bracketed argument: "which
        # scenario(s), if either", "position(s)".  English wins over brackets.
        if "(" in s and _is_english(s):
            return False
        return True
    # convert_unicode() has already turned Greek letters and symbols into macros.
    # Without this test "2\pi" looks like ordinary prose and is printed outside
    # the maths run, which the compiler then rejects (Unit 7.3 Q9).
    if any(m in MATHS_MACROS for m in SYMBOL_MACRO.findall(s)):
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


def _piece_runs(spans: list) -> list:
    """Split a line holding a ready-made \\frac / \\sqrt into maths and prose runs.

    The piece itself is copied word for word; the spans beside it are judged the
    same way every other line is, so "2\\pi" next to a fraction stays a formula.
    """
    runs: list = []
    buf: list[str] = []
    kind = None
    verbatim = False

    def flush() -> None:
        nonlocal buf, kind, verbatim
        if kind and buf:
            runs.append(("piece" if verbatim else kind, "".join(buf)))
        buf, kind, verbatim = [], None, False

    for s in spans:
        if s.get("is_latex"):
            if kind not in (None, "math") or (kind == "math" and not verbatim):
                flush()
            kind = "math"
            buf.append(s["text"])
            verbatim = True
            continue
        raw = s["text"]
        if not raw.strip():
            flush()                      # a gap separates the runs it sits between
            continue
        t = convert_unicode(raw)
        italic = bool(s.get("flags", 0) & 2)
        k = "math" if _is_math(t, italic, 0) else "text"
        if k != kind or (k == "math" and verbatim):
            flush()
            kind = k
        if k == "math":
            buf.append(t)
        elif italic and t.strip():
            buf.append(r"\textit{" + escape_text(t.strip()) + "}")
        else:
            buf.append(escape_text(t))
    flush()
    return runs


def line_to_latex(line: Line) -> str:
    """Convert one physical line into LaTeX, wrapping math runs in $...$."""
    spans = _merge_combining(line.spans)
    # A line rebuilt by reconstruct_lines() carries a finished \frac / \sqrt.
    # That piece is used verbatim, but its neighbours still need classifying --
    # treating them all as prose used to escape "2\pi" into "\textbackslash{}pi".
    if any(s.get("is_latex") for s in spans):
        return _emit(_piece_runs(spans))
    items = _script_items(spans)
    conv = []
    for kind, payload in items:
        if kind != "base":
            # a script belongs to the glyph it was raised off, so it rides along
            # with that entry rather than starting a run of its own
            wrap = kind + "{" + _render_scripts(payload).strip() + "}"
            if conv and not conv[-1]["ws"]:
                if len(conv[-1]["t"].split()) > 1:
                    # The script hangs off the last glyph, not off the clause:
                    # "at Point P2 and Point P3" would otherwise lift the whole
                    # tail into maths (Unit 5.4 Q7).
                    for piece in re.split(r"(\s+)", conv.pop()["t"]):
                        if piece:
                            conv.append({"t": piece, "math": _is_math(piece, False, 0),
                                         "ws": not piece.strip(), "raw": piece,
                                         "it": False})
                conv[-1]["t"] += wrap
                conv[-1]["math"] = True
            else:
                conv.append({"t": wrap, "math": True, "ws": False, "raw": wrap,
                             "it": False})
            continue
        s = payload[0]
        raw = s["text"]
        italic = bool(s["flags"] & 2)
        t = convert_unicode(raw)
        # A long upright run mixes prose with symbols ("... at 90^{\circ}. The object ...").
        # So does a short one ("the /2 term."), and taking the whole run as maths
        # typesets the English as an italic product.  Split it and let every
        # token decide on its own.
        if not italic and (len(t.strip()) > 12 or _mixed_upright(t)):
            for piece in re.split(r"(\s+)", t):
                if not piece:
                    continue
                conv.append({"t": piece, "math": _is_math(piece, False, 0),
                             "ws": not piece.strip(), "raw": piece})
            continue
        conv.append({"t": t, "math": _is_math(t, italic, 0), "ws": not raw.strip(),
                     "raw": raw, "it": italic})

    # wipe out a connector sitting between two formulas, else "and" is rendered
    # as an italic product of a, n and d
    for i, c in enumerate(conv):
        if _prose_word(c):
            c["math"] = False

    for i, c in enumerate(conv):
        if c["ws"]:
            # a space only counts as maths when both neighbours are maths.  A
            # connector has already been demoted, so it breaks the run cleanly.
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
        elif c["ws"]:
            buf.append(" ")
        elif c.get("it") and c["t"].strip():
            # an emphasised English word: italics, but not a product of variables
            buf.append(r"\textit{" + escape_text(c["t"].strip()) + "}")
        else:
            buf.append(escape_text(c["t"]))
    if buf:
        pieces.append(("math", "".join(buf)) if cur == "math" else ("text", "".join(buf)))

    return _emit(pieces)


def _upright_sub(body: str) -> str:
    """Physics convention: a one-letter subscript stays italic, a label does not.

    Applied here rather than only at compose time so that the stored question
    and its browser preview agree with the exported PDF.
    """
    from .latex import upright_subscripts
    return upright_subscripts(body)


def _emit(pieces: list) -> str:
    """Wrap the classified runs into math / text output."""
    out = []
    for item in pieces:
        kind, body = item[0], item[1]
        if kind in ("math", "piece"):
            if kind == "math":                 # a piece is already finished LaTeX
                body = RE_SQRT_EMPTY.sub(lambda m: "\\sqrt{" + m.group(1) + "}", body)
                body = _split_glued_macros(body)
                body = _apply_units(body)
                body = _upright_sub(body)
            body = body.strip()
            if body.endswith("\\"):
                body = body[:-1].rstrip()
            if body:
                out.append("$" + body + "$")
        elif body.strip():
            out.append(body)
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


# --------------------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------------------

def _is_blank_region(page, clip, dpi: int = 40) -> bool:
    """True when a clip contains nothing but (nearly) uniform white."""
    pix = page.get_pixmap(clip=clip, dpi=dpi, colorspace=pymupdf.csGRAY)
    data = pix.samples
    if not data:
        return True
    dark = sum(1 for b in data if b < 205)
    return dark / len(data) < 0.002


def _extract_figure(doc, page, bbox, out_path, dpi=300) -> bool:
    x0, y0, x1, y1 = bbox
    if x1 - x0 < 16 or y1 - y0 < 10:      # hairlines / ornaments, not real figures
        return False
    clip = pymupdf.Rect(x0, y0, x1, y1)
    clip = clip & page.rect
    if clip.is_empty or _is_blank_region(page, clip):
        return False                          # spacer graphics carry no information
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


IMPORT_RE = None

# question id -> the wording the PDF actually prints for it.  Filled in during
# extraction purely so scripts/audit_pages.py can reconcile every converted
# question against the original; never written into the bank.
RAW_TEXT: dict[str, str] = {}
# row key -> the wording of that single printed row
ROW_TEXT: dict[int, str] = {}


def extract_pdf(
    pdf_path: str,
    media_dir: str,
    doc_id: str,
    dpi: int = 300,
    progress=None,
) -> list:
    doc = pymupdf.open(pdf_path)
    os.makedirs(media_dir, exist_ok=True)
    _learn_vocabulary(doc)
    start = _start_page(doc)

    questions: list[Question] = []
    cur: Question | None = None
    cur_choice = None          # index into cur.choices
    pending: list = []         # printed rows swallowed by `cur`
    unit_no, unit_title = 0, ""
    topic, topic_title = "", ""
    img_counter = 0
    page_offset = None         # pdf page index -> printed book page number

    row_label_idx: list = []   # indices of choices created from a bare "A"/"B" line

    def flush():
        nonlocal cur, cur_choice
        if cur is not None:
            seen: dict[int, None] = {}
            for s in pending:
                seen.setdefault(s, None)
            RAW_TEXT[cur.id] = re.sub(
                r"\s+", " ", " ".join(ROW_TEXT[k] for k in seen
                                      if k in ROW_TEXT)).strip()
            pending.clear()
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

        lines: list[Line] = reconstruct_lines(page)

        # --- reading order: cluster items into visual rows, then sort by x -----------
        raw_items = []
        for ln in lines:
            t = ln.text
            if ln.skip or _is_chrome(t, ln.y0, ln.y1, page.rect.height):
                continue
            if not t.strip() and not any(s.get("is_latex") for s in ln.spans):
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

            # a stacked fraction: pull numerator + denominator out of the line
            frac_prefix = ""
            if ln.frac_num:
                label_spans, den_spans, rest_spans = _split_fraction(ln)
                num = convert_unicode(ln.frac_num).strip().strip("$")
                den = _latex_of_spans(den_spans, pno, ln).strip().strip("$")
                if num and den:
                    frac_prefix = rf"\frac{{{num}}}{{{den}}}"
                    ln = Line(ln.x0, ln.y0, ln.x1, ln.y1,
                              label_spans + rest_spans, pno)

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
            pending.extend(ln.srcs)

            m = RE_CHOICE.match(raw)
            if m:
                cur.choices.append({"label": m.group(1), "text": _attach_fraction(
                    frac_prefix, line_to_latex(
                        Line(ln.x0, ln.y0, ln.x1, ln.y1,
                             [{"text": m.group(2), "flags": 4,
                               "bbox": ln.spans[-1]["bbox"]}], pno)))})
                cur_choice = len(cur.choices) - 1
                continue

            m = RE_ROWLABEL.match(raw)
            if m:
                cur.choices.append({"label": m.group(1), "text": ""})
                cur_choice = len(cur.choices) - 1
                row_label_idx.append(cur_choice)
                continue

            latex = _attach_fraction(frac_prefix, line_to_latex(ln))
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
