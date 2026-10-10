#!/usr/bin/env python
"""Sanity-check every question in a bank dump for broken maths."""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "_new_extract.json")

RUN = re.compile(r"\$(.*?)\$")
WORD = re.compile(r"[A-Za-z]{4,}")
BAD = [r"\frac{}{}", r"\frac{}", r"\sqrt{}", r"^{}", r"_{}", r"\textbackslash",
       r"\vec\{", r"\hat\{", r"\{", r"\}", r"\[", r"\]"]
# words that legitimately appear inside a maths run
OPERATORS = {
    "sin", "cos", "tan", "sec", "csc", "cot", "log", "exp", "arcsin", "arccos",
    "arctan", "max", "min", "when", "none",
}
# A macro name is never an English word, and the argument of \mathrm{...} is
# meant to be read as text -- so neither counts as a stray word in maths.
MACRO = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|text|textrm|texttt|textbf|emph)"
    r"\{[^{}]*\}|\\(?:[A-Za-z]+)|\\.")

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)
qs = data["questions"] if isinstance(data, dict) else data

problems = 0


def check(qid, where, text):
    global problems
    if not text:
        return
    if text.count("$") % 2:
        print(f"DOLLAR  {qid} {where}: {text[:140]}")
        problems += 1
    for m in RUN.finditer(text):
        body = m.group(1)
        hit = False
        if body.count("{") != body.count("}"):
            print(f"BRACES  {qid} {where}: {body[:140]}")
            problems += 1
            hit = True
        for bad in BAD:
            if bad in body and not hit:
                print(f"TOKEN   {qid} {where}: {bad!r} in {body[:120]}")
                problems += 1
                hit = True
        if hit:
            continue
        inner = MACRO.sub("", body)
        for w in WORD.findall(inner):
            if w.lower() in OPERATORS:
                continue
            print(f"WORD    {qid} {where}: {w!r} in {body[:120]}")
            problems += 1
            break


for q in qs:
    check(q["id"], "stem", q["stem"])
    for c in q.get("choices") or []:
        check(q["id"], "choice " + str(c.get("label")), c.get("text", ""))

print(f"\n{len(qs)} questions checked, {problems} problems")
