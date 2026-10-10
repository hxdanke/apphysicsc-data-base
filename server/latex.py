"""LaTeX rendering, export and PDF compilation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from . import bank as bank_mod

ROOT = bank_mod.ROOT
TEMPLATE_DIR = os.path.join(ROOT, "templates")
MEDIA_DIR = bank_mod.MEDIA_DIR
DATA_DIR = bank_mod.DATA_DIR

ENGINES = ["tectonic", "xelatex", "lualatex", "pdflatex"]

# --------------------------------------------------------------------------------------
# preamble
#
# A practice set is the questions and nothing else: A4, Times New Roman 11pt,
# no cover title, no unit or topic heading, no page number, no running head or
# foot and no provenance line under a question.  Short multiple-choice options
# are set inline on one line, as in the printed book.
# --------------------------------------------------------------------------------------

_HEAD = r"""\documentclass[11pt,a4paper]{article}
\usepackage[left=0.72in,right=0.72in,top=0.70in,bottom=0.80in]{geometry}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage[inline]{enumitem}
@@FONTS@@\graphicspath{{@@DATA@@/}{@@MEDIA@@/}}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
% math pulled from the PDF carries literal spaces; keep them visible
\AtBeginDocument{\setlength{\mathsurround}{0pt}}
\thinmuskip=4mu \medmuskip=5mu plus 2mu minus 2mu \thickmuskip=7mu plus 3mu
\newcommand{\fig}[2][0.5]{\begin{center}\includegraphics[width=#1\linewidth]{#2}\end{center}}
\begin{document}
"""

# Times New Roman everywhere it exists: text, quantities (italic), units and
# multi-letter labels (upright), digits and the ordinary ASCII operators.  Only
# the symbols Times New Roman has no glyph for (integral, radical, sigma, ...)
# come from a real maths font, which supplies the sizes and spacing they need.
_FONTS_XE = r"""\usepackage{fontspec}
\usepackage{unicode-math}
\IfFontExistsTF{Times New Roman}{\setmainfont{Times New Roman}}{\setmainfont{TeX Gyre Termes}}
\IfFontExistsTF{TeX Gyre Termes Math}{\setmathfont{TeX Gyre Termes Math}}{%
  \IfFontExistsTF{Cambria Math}{\setmathfont{Cambria Math}}{}}
\IfFontExistsTF{Times New Roman}{%
  \setmathfont{Times New Roman}[range=up/{latin,Latin,greek,Greek,num}]%
  \setmathfont{Times New Roman Italic}[range=it/{latin,Latin,greek,Greek}]%
  \setmathfont{Times New Roman}[range={"0028-"0029,"002B-"002F,"003A-"003E,"005B,"005D,"007C,"2212}]%
}{}
"""

_FONTS_PDF = r"""\usepackage[T1]{fontenc}
\usepackage{mathptmx}
"""

POSTAMBLE = r"\end{document}" + "\n"


def _preamble(title: str = "", subtitle: str = "", xe: bool = True) -> str:
    """Full preamble; `xe` picks the fontspec route (tectonic/xelatex/lualatex).

    `title` and `subtitle` are accepted for backwards compatibility but are no
    longer typeset: a practice set is the questions and nothing else.
    """
    return (_HEAD
            .replace("@@FONTS@@", _FONTS_XE if xe else _FONTS_PDF)
            .replace("@@DATA@@", DATA_DIR.replace("\\", "/"))
            .replace("@@MEDIA@@", MEDIA_DIR.replace("\\", "/")))

# --------------------------------------------------------------------------------------
# TeX command vocabulary
#
# The PDF rasterises Greek letters and operators, so the extractor rebuilds them
# from Unicode.  Sometimes the following letter run is glued on ("\Deltax"), which
# is an undefined control sequence for a real engine.  TEX_MACROS is the set of
# names we guarantee to be valid, used to split such runs back apart.
# --------------------------------------------------------------------------------------

TEX_MACROS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
    "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi",
    "Psi", "Omega",
    "infty", "partial", "nabla", "cdot", "cdots", "ldots", "times", "div",
    "sqrt", "frac", "dfrac", "tfrac", "vec", "hat", "bar", "widehat", "tilde",
    "overline", "underline", "angle", "circ", "degree", "pm", "mp", "leq",
    "geq", "neq", "approx", "sim", "equiv", "propto", "perp", "parallel",
    "sum", "prod", "int", "oint", "lim", "log", "ln", "exp", "sin", "cos",
    "tan", "sec", "csc", "cot", "arcsin", "arccos", "arctan", "sinh", "cosh",
    "tanh", "mathrm", "mathbf", "mathit", "text", "textbf", "textit",
    "left", "right", "big", "Big", "bigg", "Bigg", "quad", "qquad", "ell",
    "hbar", "prime", "ast", "star", "bullet", "oplus", "otimes", "subset",
    "supset", "cup", "cap", "in", "notin", "forall", "exists", "neg", "land",
    "lor", "to", "rightarrow", "leftarrow", "Rightarrow", "Leftarrow",
    "leftrightarrow", "uparrow", "downarrow", "mid", "cdotp", "colon",
}

# Only Greek-letter macros get glued by the extractor, and only to a short
# identifier fragment.  Enumerating the exact spellings keeps legitimate long
# names such as \includegraphics safe from a naive prefix split.
_GREEK = ("Delta", "Omega", "Theta", "Lambda", "Sigma", "Upsilon", "Phi", "Psi",
          "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta",
          "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
          "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega")
_TAILS = tuple("xyztrhsvp" + "EVKLMABRFT" + "012")
GLUED_MACROS = {g + t for g in _GREEK for t in _TAILS}
GLUED_MACROS -= TEX_MACROS          # never touch a name that is already valid
RE_GLUED_MACRO = re.compile(r"\\(" + "|".join(sorted(GLUED_MACROS, key=len, reverse=True))
                            + r")(?![A-Za-z])")


def _rebuild_glued(name: str) -> str:
    for root in sorted(_GREEK, key=len, reverse=True):
        if name.startswith(root) and name != root:
            return "\\" + root + " " + name[len(root):]
    return "\\" + name


def split_glued_macros(text: str) -> str:
    """``\\Deltax`` -> ``\\Delta x``; leave every valid name alone."""
    return RE_GLUED_MACRO.sub(lambda m: _rebuild_glued(m.group(1)), text)


RE_IMG = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


# --------------------------------------------------------------------------------------
# pieces
# --------------------------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%")


def _paths(title: str, subtitle: str) -> dict:
    return {
        "data": DATA_DIR.replace("\\", "/"),
        "media": MEDIA_DIR.replace("\\", "/"),
        "title": _esc(title),
        "subtitle": _esc(subtitle),
    }


def _engine_is_xe() -> bool:
    """True when we will compile with tectonic/xelatex/lualatex (fontspec route)."""
    engine = find_engine()
    if not engine:
        return True
    base = os.path.basename(engine).lower()
    return not base.startswith("pdftex") and "pdflatex" not in base


RE_IMG_TOKEN = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")

# choices that fit on one line are set inline, just like in the printed book
INLINE_CHOICE_MAX = 34

# question list: number flush against the left margin, stem indented by ~1cm
# (measured: label at x=49.6pt, stem at x=77.9pt on an A4 page)
ITEMS_BEGIN = (r"\begin{enumerate}[leftmargin=1cm,labelwidth=0.85cm,labelsep=0.35em,"
               r"align=right,itemsep=8pt,parsep=0pt,topsep=2pt]")

# option text is one logical column; a figure that belongs to an option sits in
# a second column (2in) so it does not push the paragraph spacing around
ITEMS_CHOICE_GRID = (r"\begin{enumerate}[label=(\Alph*),labelwidth=1.35em,labelsep=0.45em,"
                     r"leftmargin=1.85em,itemindent=0cm,listparindent=0pt,parsep=0pt,"
                     r"itemsep=1pt,topsep=2pt]")


# Physics convention, and the one the user asked for: a one-letter subscript is
# a quantity and stays italic (v_{x}), anything longer is a label and is
# upright (a_{avg}, P_{AB}, v_{rot,S}).  Digits are upright already.
RE_SUB_GROUP = re.compile(r"_\{([^{}$\\]*)\}")


def upright_subscripts(body: str) -> str:
    def sub(m):
        inner = m.group(1).strip()
        if not inner or "\\" in inner:
            return m.group(0)
        core = inner.replace(" ", "")
        if len(core) <= 1 or core.isdigit():
            return m.group(0)
        return "_{\\mathrm{" + inner + "}}"
    return RE_SUB_GROUP.sub(sub, body)


RE_TRAIL_IMG = re.compile(r"(?:\s*\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^{}]*\})\s*$")


def _choices_latex(choices: list) -> str:
    if not choices:
        return ""
    texts = [tex_safe((c.get("text") or "").strip()) for c in choices]
    # an option whose figure is inlined runs off the line: always use a grid there
    has_img = any("\\includegraphics" in t for t in texts)
    inline = (not has_img and len(texts) >= 2
              and all(len(t) <= INLINE_CHOICE_MAX for t in texts))
    if inline:
        out = ["\\begin{enumerate*}[label=(\\Alph*),itemjoin=\\quad,after=\\strut]"]
        out += [f"  \\item {t}" if t else "  \\item ~" for t in texts]
        out.append("\\end{enumerate*}")
        return "\n".join(out)
    if has_img:
        # option text in one column with its figure right underneath, so a tall
        # image cannot leave a gap after the last option.  Labels are written by
        # hand so the figure column stays clear of the (A)/(B) markers.
        out = [ITEMS_CHOICE_GRID]
        for lab, t in zip([c.get("label") or "" for c in choices], texts):
            body = RE_TRAIL_IMG.sub("", t).strip()
            img = RE_IMG_TOKEN.search(t)
            marker = f"\\item[{_choice_label(lab)}]"
            cells = body if body else "~"
            if img:
                cells += "\\par\\vspace{2pt}" + img.group(0)
            out.append("  " + marker + " " + cells)
        out.append("\\end{enumerate}")
        return "\n".join(out)
    out = ["\\begin{enumerate}[label=(\\Alph*),itemsep=2pt,topsep=2pt,leftmargin=2.4em]"]
    out += [f"  \\item {t}" if t else "  \\item ~" for t in texts]
    out.append("\\end{enumerate}")
    return "\n".join(out)


def _choice_label(lab: str) -> str:
    """Normalise an option label to the printed form, e.g. ``B`` -> ``(B)``."""
    m = re.search(r"[A-Za-z]", lab or "")
    return f"({m.group(0)})" if m else "(?)"


# --------------------------------------------------------------------------------------
# TeX hardening
#
# A handful of questions could not be recovered perfectly from the PDF and end up
# with cascaded scripts such as ``v^{0}^{t}^{cos}``.  KaTeX tolerates that, but a
# real TeX engine aborts with "Double superscript" and the whole export dies.
# We give every later group an empty base so the run still compiles.
# --------------------------------------------------------------------------------------

RE_DSUP_BRACE = re.compile(r"(\^\{[^{}]*\})(?=\s*\^\{)")
RE_DSUB_BRACE = re.compile(r"(\_\{[^{}]*\})(?=\s*\_\{)")
RE_DSUP_BARE = re.compile(r"(\^\{[^{}]*\}|\^\w)(?=\s*\^[^{\s])")
RE_DSUB_BARE = re.compile(r"(\_\{[^{}]*\}|\_\w)(?=\s*\_[^{\s])")


# ``v^{0}^{t}^{cos}`` -> ``v^{0 t cos}``; a real engine refuses the original.
RE_CAS_SUP = re.compile(r"\^\{([^{}]*)\}\s*\^\{([^{}]*)\}")
RE_CAS_SUB = re.compile(r"_\{([^{}]*)\}\s*_\{([^{}]*)\}")

# ``\mathrm{g}_{E} ^{\mathrm{g}}_{E}`` -- the same script marker used twice in a
# row with no base in between ("Double subscript" for TeX).  Only a *repeat* is
# rewritten, so a healthy ``v_{0}^{2}`` is never touched.
RE_REPEAT_SUB = re.compile(r"_\{[^{}]*\}\s*_")
RE_REPEAT_SUP = re.compile(r"\^\{[^{}]*\}\s*\^")


def _read_group(body: str, start: int) -> tuple[str, int] | None:
    """Read a balanced ``{...}`` beginning at ``start``."""
    if start >= len(body) or body[start] != "{":
        return None
    depth = 0
    for i in range(start, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                return body[start + 1:i], i + 1
    return None


def _fold_repeat(text: str, marker: str) -> str:
    """Collect a run of repeated sub/superscripts into one group."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == marker:
            grp = _read_group(text, i + 1)
            if grp is not None:
                pieces = [grp[0]]
                j = grp[1]
                while True:
                    k = j
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == marker:
                        nxt = _read_group(text, k + 1)
                        if nxt is not None:
                            pieces.append(nxt[0])
                            j = nxt[1]
                            continue
                    break
                if len(pieces) > 1:
                    out.append(marker + "{" + " ".join(p for p in pieces if p) + "}")
                else:
                    out.append(text[i:j])
                i = j
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def collapse_alternating(text: str) -> str:
    for marker in ("^", "_"):
        for _ in range(8):
            new = _fold_repeat(text, marker)
            if new == text:
                break
            text = new
    return text


# ``\frac{3}{Evaluate the $\int}`` -- the PDF put a paragraph of prose inside a
# fraction slot.  Whatever the extractor produced, an unbalanced group must never
# reach the engine, so brace it up as a last resort.
# TeX allows one ^ and one _ per base.  A formula rebuilt from a badly stacked
# PDF slice can carry several of each; every extra one is demoted to a plain
# group so the run still compiles (it is a garbled slice either way).
def demote_extra_scripts(text: str) -> str:
    out = []
    i = 0
    n = len(text)
    seen_sup = False
    seen_sub = False
    while i < n:
        ch = text[i]
        if ch in "_^":
            grp = _read_group(text, i + 1)
            if grp is not None:
                already = seen_sup if ch == "^" else seen_sub
                if ch == "^":
                    seen_sup = True
                else:
                    seen_sub = True
                if already:
                    out.append("{" + grp[0] + "}")
                else:
                    out.append(ch + "{" + grp[0] + "}")
                i = grp[1]
                continue
        if ch == "\\":
            m = re.match(r"\\[A-Za-z]+", text[i:])
            if m:
                out.append(m.group(0))
                # a new command is a new base ("\cos^{\theta}")
                seen_sup = seen_sub = False
                i += m.end()
                continue
        if ch in ")]}":
            seen_sup = seen_sub = False
        out.append(ch)
        i += 1
    return "".join(out)


def balance_braces(text: str) -> str:
    """Make a maths run brace-balanced so the engine can still typeset it.

    A ``\\frac{3}{Evaluate the $\\int} \\omega(t) 1 dt`` slice from the book ends
    up with a stray ``}``; dropping unmatched closers is enough to recover it.
    """
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if depth > 0:
        return text + "}" * depth
    if depth < 0:                       # more closers than openers: drop the extras
        out = []
        depth = 0
        for ch in text:
            if ch == "{":
                depth += 1
                out.append(ch)
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    out.append(ch)
                # else: stray closer, drop it
            else:
                out.append(ch)
        return "".join(out)
    return text


def collapse_script_runs(text: str) -> str:
    """Merge ``_{E} ^{g}_{E}`` -- the *same* marker twice in one run -- into a
    single exponent.  A healthy ``v_{0}^{2}`` uses each marker once and is left
    untouched, and a leading base character also disqualifies the run."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] not in "_^" or (i and text[i - 1] not in " \t"):
            out.append(text[i])
            i += 1
            continue
        run = []
        j = i
        while j < n and text[j] in "_^":
            grp = _read_group(text, j + 1)
            if grp is None:
                break
            run.append((text[j], grp[0]))
            j = grp[1]
            while j < n and text[j] in " \t":
                j += 1
        marks = [m for m, _ in run]
        if len(run) >= 2 and len(marks) != len(set(marks)):
            pieces = [v for _, v in run if v]
            out.append("^{" + " ".join(pieces) + "}")
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


RE_MATH_SPAN = re.compile(r"\$([^$]*)\$")


RE_MATH_DOLLAR = re.compile(r"\$")


# An ordinary space is invisible in maths, so a unit that the PDF printed next
# to a number ("4 m/s 45°") would come out glued ("4 m/s45°").  Promote the
# space to an explicit one on both sides of an upright unit.
RE_SPACE_BEFORE_UNIT = re.compile(r"(?<=[0-9)\]}])\s+(?=\\mathrm\{)")
RE_UNIT_BEFORE_NUM = re.compile(
    r"(\\mathrm\{[^{}]*\}(?:\s*\^\{[^{}]*\})?)(?<!\\)[ \t]+(?=[0-9(])")


def _space_units(body: str) -> str:
    body = RE_SPACE_BEFORE_UNIT.sub(r"\\ ", body)
    return RE_UNIT_BEFORE_NUM.sub(r"\1\\ ", body)


def _safe_math_body(body: str) -> str:
    body = RE_MATH_DOLLAR.sub(" ", body)   # an inner $ would close the run early
    body = split_glued_macros(body)
    body = collapse_alternating(body)
    body = collapse_script_runs(body)
    body = upright_subscripts(body)
    body = demote_extra_scripts(body)
    body = balance_braces(body)
    body = _space_units(body)
    body = re.sub(r"\s{2,}", " ", body)
    return body.strip()


# a maths run that opens but never closes (the PDF swallowed the delimiter)
RE_OPEN_MATH = re.compile(r"\$([^$\n]*)$")


def _scan_math(text: str) -> list:
    """Split into ('text'|'math', body) pieces, honouring the delimiters found."""
    pieces = []
    buf = []
    i = 0
    in_math = False
    while i < len(text):
        if text[i] == "$":
            if in_math:
                pieces.append(("math", "".join(buf)))
                buf = []
                in_math = False
            else:
                if buf:
                    pieces.append(("text", "".join(buf)))
                    buf = []
                in_math = True
            i += 1
            continue
        if in_math and text[i] == "$":
            i += 1
            continue
        buf.append(text[i])
        i += 1
    pieces.append(("math" if in_math else "text", "".join(buf)))
    return pieces


def tex_safe(text: str) -> str:
    """Make a math snippet survive a strict TeX engine.

    Delimiters are located first, then every maths body is hardened on its own so
    ordinary prose is never rewritten.  When the delimiter count is odd the
    original book slice lost a ``$`` somewhere; the safest recovery is to treat
    the whole field as one maths run and let ``balance_braces`` close it up.
    """
    if not text:
        return text
    if text.count("$") % 2:
        return "$" + _safe_math_body(text.replace("$", " ")) + "$"
    out = []
    for kind, body in _scan_math(text):
        if kind == "math":
            out.append("$" + _safe_math_body(body) + "$")
        else:
            # a stray brace in prose is a maths leftover; it would otherwise close
            # the enclosing environment.  Braces belonging to a command argument
            # (\includegraphics{...}) are left alone.
            out.append(_drop_stray_braces(body))
    return "".join(out)


# ``\command{...}`` -- the braces here are structural, everything else is noise
RE_CMD_ARGS = re.compile(r"\\[A-Za-z]+\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")


def _drop_stray_braces(text: str) -> str:
    keep = []
    out = []
    i = 0
    while i < len(text):
        m = RE_CMD_ARGS.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = text[i]
        if ch in "{}":
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
    for _ in range(6):
        new = RE_CAS_SUP.sub(r"^{\1 \2}", out)
        new = RE_CAS_SUB.sub(r"_{\1 \2}", new)
        if new == out:
            break
        out = new
    for _ in range(6):
        new = RE_DSUP_BRACE.sub(r"\1\\,{}", out)
        new = RE_DSUB_BRACE.sub(r"\1\\,{}", new)
        new = RE_DSUP_BARE.sub(r"\1\\,{}", new)
        new = RE_DSUB_BARE.sub(r"\1\\,{}", new)
        if new == out:
            break
        out = new
    return out


def question_body(q: dict, show_answer: bool = False, show_solution: bool = False,
                  indent_choices: bool = True) -> str:
    """LaTeX snippet for a single question."""
    lines = []
    stem = tex_safe((q.get("stem") or "").strip())
    if stem:
        lines.append(stem)
        lines.append("")
    choices = q.get("choices") or []
    if choices:
        if indent_choices:
            lines.append(_choices_latex(choices))
        else:
            for c in choices:
                txt = tex_safe((c.get("text") or "").strip())
                lines.append(f"\\textbf{{({c.get('label','')})}}\\ {txt}\\\\[2pt]")
        lines.append("")
    if show_answer and q.get("answer"):
        lines.append(tex_safe(f"\\textbf{{Answer: {q['answer']}}}"))
        lines.append("")
    if show_solution and (q.get("solution") or "").strip():
        lines.append("\\paragraph*{Solution.} " + tex_safe(q["solution"].strip()))
        lines.append("")
    return "\n".join(lines)


def build_document(questions: list, title: str = "AP Physics C: Mechanics Practice Set",
                   subtitle: str = "", show_answer: bool = False, show_solution: bool = False,
                   group_by_topic: bool = True, instructions: str = "") -> str:
    out = [_preamble(title, subtitle, xe=_engine_is_xe())]
    if instructions:
        out.append(instructions + "\n")

    # grouping only fixes the order; with no printed headings the numbering has
    # to run straight through from 1, so there is a single list either way
    if group_by_topic:
        groups: dict = {}
        order: list = []
        for q in questions:
            key = (q.get("unit", 0), q.get("topic", ""), q.get("topic_title", ""))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(q)
        ordered: list = []
        for key in sorted(order):
            ordered.extend(sorted(groups[key], key=lambda x: x.get("number", 0)))
    else:
        ordered = list(questions)

    out.append(ITEMS_BEGIN)
    for q in ordered:
        out.append("  \\item " + question_body(
            q, show_answer, show_solution).replace("\n", "\n  "))
    out.append("\\end{enumerate}\n")

    out.append(POSTAMBLE)
    return "\n".join(out)


def question_tex(q: dict, show_answer: bool = True, show_solution: bool = True) -> str:
    """A standalone, compilable document for one question (used by the preview pane)."""
    head = _preamble(q.get("id", "Question"), "", xe=_engine_is_xe())
    body = question_body(q, show_answer, show_solution)
    return head + body + POSTAMBLE


def used_media(questions: list) -> list:
    """Absolute paths of every figure referenced by the given questions."""
    found = []
    for q in questions:
        text = (q.get("stem") or "") + " " + " ".join(
            (c.get("text") or "") for c in (q.get("choices") or []))
        if (q.get("solution") or ""):
            text += " " + q["solution"]
        for rel in RE_IMG.findall(text):
            rel = rel.strip()
            cand = os.path.join(ROOT, rel) if not os.path.isabs(rel) else rel
            if os.path.exists(cand):
                found.append(cand)
    return found


# --------------------------------------------------------------------------------------
# compilation
# --------------------------------------------------------------------------------------

def find_engine() -> str | None:
    for name in ENGINES:
        if shutil.which(name):
            return name
    # a vendored tectonic (tools/) that was downloaded for local development
    local = os.path.join(ROOT, "tools", "tectonic.exe")
    if os.path.exists(local):
        return local
    local = os.path.join(ROOT, "tools", "tectonic")
    if os.path.exists(local):
        return local
    return None


def compile_pdf(tex_source: str, workdir: str | None = None, jobname: str = "document") -> dict:
    """Write `tex_source` to a temp dir and run a TeX engine on it.

    Returns {"ok": bool, "pdf": path|None, "log": str, "engine": str}
    """
    engine = find_engine()
    if not engine:
        return {
            "ok": False, "pdf": None, "engine": None,
            "log": ("No TeX engine found. Install one of: " + ", ".join(ENGINES) +
                    "\nRecommended: tectonic (https://tectonic-typesetting.github.io/). "
                    "Place tectonic.exe in ./tools/ or put it on your PATH."),
        }
    tmp = workdir or tempfile.mkdtemp(prefix="qbank-")
    os.makedirs(tmp, exist_ok=True)
    tex_path = os.path.join(tmp, jobname + ".tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_source)

    cmd = [engine, "--outdir", tmp, tex_path] if os.path.basename(engine).startswith("tectonic") \
        else [engine, "-interaction=nonstopmode", "-halt-on-error",
              "-output-directory", tmp, tex_path]
    try:
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, timeout=300,
                              text=True, errors="replace")
    except FileNotFoundError:
        return {"ok": False, "pdf": None, "engine": engine, "log": "engine binary missing"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "pdf": None, "engine": engine, "log": "compilation timed out"}

    pdf_path = os.path.join(tmp, jobname + ".pdf")
    log = (proc.stdout or "") + (proc.stderr or "")
    # Keep the whole log (capped) -- tectonic reports genuine errors well before
    # the trailing font warnings, so a tail-only view hides them.
    if len(log) > 40000:
        log = log[:6000] + "\n... (truncated) ...\n" + log[-14000:]
    if os.path.exists(pdf_path):
        return {"ok": True, "pdf": pdf_path, "engine": os.path.basename(engine), "log": log}
    return {"ok": False, "pdf": None, "engine": os.path.basename(engine), "log": log}
