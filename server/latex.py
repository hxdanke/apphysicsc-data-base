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

PREAMBLE = r"""\documentclass[11pt,letterpaper]{article}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{multicol}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{fancyhdr}
\usepackage{titlesec}
\graphicspath{{%(data)s/}{%(media)s/}}
\setlength{\parindent}{0pt}
\pagestyle{fancy}
\fancyhf{}
\fancyfoot[C]{\thepage}
\renewcommand{\headrulewidth}{0pt}
\title{%(title)s}
\author{%(subtitle)s}
\date{}
\newcommand{\fig}[2][0.5]{\begin{center}\includegraphics[width=#1\linewidth]{#2}\end{center}}
\begin{document}
\maketitle
"""

POSTAMBLE = r"\end{document}" + "\n"

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


def question_body(q: dict, show_answer: bool = False, show_solution: bool = False,
                  indent_choices: bool = True) -> str:
    """LaTeX snippet for a single question."""
    lines = []
    stem = (q.get("stem") or "").strip()
    if stem:
        lines.append(stem)
        lines.append("")
    choices = q.get("choices") or []
    if choices:
        if indent_choices:
            lines.append("\\begin{enumerate}[label=(\\Alph*),itemsep=2pt,topsep=2pt,leftmargin=2.2em]")
            for c in choices:
                txt = (c.get("text") or "").strip()
                lines.append(f"  \\item {txt}" if txt else "  \\item ~")
            lines.append("\\end{enumerate}")
        else:
            for c in choices:
                txt = (c.get("text") or "").strip()
                lines.append(f"\\textbf{{({c.get('label','')})}}\\ {txt}\\\\[2pt]")
        lines.append("")
    if show_answer and q.get("answer"):
        lines.append(f"\\textbf{{Answer: {q['answer']}}}")
        lines.append("")
    if show_solution and (q.get("solution") or "").strip():
        lines.append("\\paragraph*{Solution.} " + q["solution"].strip())
        lines.append("")
    if q.get("source"):
        src = q["source"]
        bits = [str(src.get("doc", ""))]
        if src.get("book_page"):
            bits.append(f"p.{src['book_page']}")
        lines.append("\\begin{flushright}\\tiny " + ", ".join(bits) + "\\end{flushright}")
    return "\n".join(lines)


def build_document(questions: list, title: str = "AP Physics C: Mechanics Practice Set",
                   subtitle: str = "", show_answer: bool = False, show_solution: bool = False,
                   group_by_topic: bool = True, instructions: str = "") -> str:
    out = [PREAMBLE % _paths(title, subtitle)]
    if instructions:
        out.append(instructions + "\n")

    if group_by_topic:
        groups: dict = {}
        order: list = []
        for q in questions:
            key = (q.get("unit", 0), q.get("topic", ""), q.get("topic_title", ""))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(q)
        for key in sorted(order):
            groups[key].sort(key=lambda x: x.get("number", 0))
            unit, topic, ttitle = key
            heading = f"Unit {unit}"
            if topic:
                heading += f" \\quad {topic}"
            if ttitle:
                heading += f" -- {ttitle}"
            out.append(f"\\section*{{{heading}}}")
            out.append("\\begin{enumerate}[leftmargin=2.2em,itemsep=6pt]")
            for q in groups[key]:
                out.append("  \\item " + question_body(
                    q, show_answer, show_solution).replace("\n", "\n  "))
            out.append("\\end{enumerate}\n")
    else:
        out.append("\\begin{enumerate}[leftmargin=2.2em,itemsep=6pt]")
        for q in questions:
            out.append("  \\item " + question_body(
                q, show_answer, show_solution).replace("\n", "\n  "))
        out.append("\\end{enumerate}\n")

    out.append(POSTAMBLE)
    return "\n".join(out)


def question_tex(q: dict, show_answer: bool = True, show_solution: bool = True) -> str:
    """A standalone, compilable document for one question (used by the preview pane)."""
    head = PREAMBLE % _paths(q.get("id", "Question"), "")
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
    if os.path.exists(pdf_path):
        return {"ok": True, "pdf": pdf_path, "engine": os.path.basename(engine), "log": log[-6000:]}
    return {"ok": False, "pdf": None, "engine": os.path.basename(engine), "log": log[-6000:]}
