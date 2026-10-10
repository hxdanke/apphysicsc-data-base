"""Repair the LaTeX artefacts left behind by the PDF extractor.

The extractor walks PDF text spans, so anything that was stacked vertically in
the source (fractions, radicals, superscripts on a missing base) loses its
structure.  The three recurring artefacts are:

1. ``\\textbackslash{}pi``      -- a literal backslash that should be ``\\pi``.
2. ``\\ ^{1} 2\\ ^{gt}^{2}``    -- a stacked fraction turned into a superscript
   with no base, followed by the denominator as its own maths run.
3. ``$$`` / ``\\sqrt{}``        -- empty maths runs and empty radicals.

All three make KaTeX bail out.  ``repair()`` is safe to run repeatedly and is
used both by the ingest pipeline and by ``scripts/normalize_bank.py``.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# 1. literal backslashes that were meant to introduce a macro
# --------------------------------------------------------------------------- #

_MACROS = {
    "pi", "theta", "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon",
    "zeta", "eta", "iota", "kappa", "lambda", "mu", "nu", "xi", "rho", "sigma",
    "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega", "Gamma", "Delta",
    "Theta", "Lambda", "Xi", "Sigma", "Phi", "Psi", "Omega",
    "times", "cdot", "div", "pm", "mp", "approx", "neq", "leq", "geq",
    "infty", "partial", "nabla", "sum", "int", "sqrt", "hat", "vec", "bar",
    "overline", "angle", "degree", "circ", "perp", "parallel", "propto",
    "equiv", "sim", "ell", "mu", "Omega",
}

RE_BACKSLASH = re.compile(r"\\textbackslash\{\}\s*([A-Za-z]+)")
RE_BRACE_BACKSLASH = re.compile(r"\{\\textbackslash\{\}\}\s*([A-Za-z]+)")


def _fix_backslashes(s: str) -> str:
    def sub(m):
        name = m.group(1)
        return "\\" + name if name in _MACROS else m.group(0)
    s = RE_BRACE_BACKSLASH.sub(sub, s)
    s = RE_BACKSLASH.sub(sub, s)
    s = _split_glued(s)
    return s


# ``\Deltat`` -> ``\Delta t``; a strict engine reads the glued run as one name.
# Only the *exact* glued spellings below are rewritten -- a prefix rule would also
# split legitimate names such as \includegraphics ("\in" + "cludegraphics").
_GLUE_ROOTS = ("Delta", "Omega", "Theta", "Lambda", "Sigma", "alpha", "beta",
               "gamma", "delta", "epsilon", "theta", "lambda", "omega", "sigma",
               "phi", "mu", "pi", "rho", "tau")
_GLUE_NAMES = set()
for _root in _GLUE_ROOTS:
    for _tail in ("x", "y", "z", "t", "r", "h", "s", "v", "p", "E", "K", "L",
                  "A", "B", "M", "R", "T", "V", "0", "1", "2"):
        _GLUE_NAMES.add(_root + _tail)
RE_GLUED = re.compile(r"\\(" + "|".join(sorted(_GLUE_NAMES, key=len, reverse=True))
                      + r")(?![A-Za-z])")


def _split_glued(s: str) -> str:
    """``\\Deltat`` -> ``\\Delta t``, ``\\alphar`` -> ``\\alpha r``."""
    def sub(m):
        name = m.group(1)
        for root in sorted(_GLUE_ROOTS, key=len, reverse=True):
            if name.startswith(root) and name != root:
                return "\\" + root + " " + name[len(root):]
        return m.group(0)
    return RE_GLUED.sub(sub, s)


# --------------------------------------------------------------------------- #
# 2. merge neighbouring maths runs that used to be one formula
# --------------------------------------------------------------------------- #

RE_ADJACENT = re.compile(r"\$([^$]*)\$\s*\$\s*([^$]*)\$")

# ``$a = (t-6)$ m/s$^{2}$`` -- the unit fell out of the maths run when the
# connector filter reclassified the span that used to hold it.  Pull the unit
# back in so it is typeset upright with the value it belongs to.
_UNIT_WORD = (r"(?:m/s|kg/s|N/m|rad/s|kg|mg|cm|mm|km|nm|mL|Hz|Pa|min|rev|rad|ms|"
              r"N|J|W|m|s|g|h|L)")
# The unit may sit outside the maths ("$v$ m/s"), and its exponent may be in a
# maths run of its own ("m/s$^{2}$").  Match the value run, the bare unit and an
# optional exponent run, then fold all three back into a single maths run.
RE_UNIT_BETWEEN = re.compile(
    r"\$([^$]*)\$[ ]*(" + _UNIT_WORD + r")"
    r"(?:[ ]*\$\s*\^\{([^{}]*)\}\s*\$|[ ]*\^\s*\{([^{}]*)\})?"
    r"(?=[\s,.;:?)\]]|\$)")


# ``the equations a$_{x} = ...`` -- the base letter was classified as prose and
# left outside the maths run, so the quantity prints upright.  A lone letter
# immediately in front of a subscripted run is always that run's base: move the
# delimiter so the whole thing becomes one formula again.
RE_STRAY_BASE = re.compile(r"(?<![A-Za-z\\{])([A-Za-z])\$_\{")


def fix_stray_bases(s: str) -> str:
    return RE_STRAY_BASE.sub(r"$\1_{", s)


def merge_math_runs(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = RE_ADJACENT.sub(lambda m: f"${m.group(1)} {m.group(2)}$", s)
    # an empty run "$ $" carries nothing
    s = re.sub(r"\$\s*\$", "", s)
    return s


def pull_units_into_math(s: str) -> str:
    """Re-attach a stray unit that sits between a value and the next formula."""

    def sub(m):
        body, unit = m.group(1), m.group(2)
        sup = m.group(3) if m.group(3) is not None else m.group(4)
        out = body + "\\ " + "\\mathrm{" + unit + "}"
        if sup is not None:
            out += "^{" + sup + "}"
        return "$" + out + "$"

    prev = None
    while prev != s:
        prev = s
        s = RE_UNIT_BETWEEN.sub(sub, s)
    return s


# --------------------------------------------------------------------------- #
# 3. superscripts with no base -> stacked fraction (or plain concatenation)
# --------------------------------------------------------------------------- #

RE_DEN_GROUP = re.compile(r"\s*\{([^{}]*)\}")
RE_DEN_ATOM = re.compile(r"\s*(\d+(?:\.\d+)?|[A-Za-z]+)")
RE_DEN_CMD = re.compile(r"\s*\\([a-zA-Z]+)\s*\{([^{}]*)\}")

_BASE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789}]")
_SPACING = " \t\\,"


def _prev_significant(out: list[str]) -> str:
    """Last emitted character, ignoring the `\\ ` spacers the extractor adds."""
    for chunk in reversed(out):
        for ch in reversed(chunk):
            if ch not in _SPACING:
                return ch
    return ""


def _brace_group(body: str, start: int) -> tuple[str, int] | None:
    """Return (content, index_after_closing_brace) for a {...} group at `start`."""
    if start >= len(body) or body[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(body):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                return body[start + 1:i], i + 1
        i += 1
    return None


def _skip_spacing(body: str, i: int) -> int:
    while i < len(body) and body[i] in _SPACING:
        i += 1
    return i


def fix_empty_superscripts(body: str) -> str:
    """Rewrite `^{...}` groups that have no base inside a maths body.

    A stacked ``\\frac{a}{b}`` survives extraction as ``^{a} b`` (numerator as a
    superscript with no base, denominator as its own maths run), so a bare
    caret group followed by a token is turned back into a fraction.  Anything
    else is emitted literally, with the group's content inlined.
    """
    out: list[str] = []
    i = 0
    n = len(body)
    cascade = False   # the previous group was structural -> next ^ is also bare

    while i < n:
        if body[i] == "^":
            j = i + 1
            if j < n and body[j] == "{":
                grp = _brace_group(body, j)
                if grp is not None:
                    num, after = grp[0].strip(), grp[1]
                    # `^{)}`, `^{-}`, `^{(}` ... : delimiters are never exponents
                    structural = (not num) or (
                        len(num) == 1 and not num.isalnum())
                    prev_ok = (cascade or structural
                               or _prev_significant(out) not in _BASE_CHARS
                               or re.search(r"\\frac\{[^{}]*\}\{[^{}]*\}$",
                                            "".join(out).rstrip(_SPACING)))
                    if not prev_ok:
                        out.append(body[i])
                        i += 1
                        continue
                    k = _skip_spacing(body, after)

                    # denominator: \cmd{...} | { ... } | bare number/word
                    # (a delimiter such as `^{)}` never starts a fraction)
                    if structural:
                        out.append(num)
                        i = after
                        cascade = True
                        continue
                    den = None
                    end = k
                    d = RE_DEN_CMD.match(body, k)
                    if d:
                        den, end = f"\\{d.group(1)}{{{d.group(2)}}}", d.end()
                    else:
                        brace = _brace_group(body, k)
                        if brace and brace[0].strip():
                            den, end = brace[0].strip(), brace[1]
                        else:
                            d = RE_DEN_ATOM.match(body, k)
                            if d:
                                den, end = d.group(1), d.end()
                                rest = body[end:].lstrip(_SPACING)
                                # `2 ^{..}` -> 2 is the denominator of a stack,
                                # `x^{2}`   -> x keeps its superscript
                                if (rest.startswith("^") and
                                        not re.fullmatch(r"[0-9]+", num)):
                                    den = None

                    if den is not None and ("$" in den or len(den) > 24):
                        den = None

                    if den is not None:
                        out.append(f"\\frac{{{num}}}{{{den}}}")
                        i = end
                        cascade = True
                        continue

                    out.append(num)
                    i = after
                    cascade = not (num and num[-1].isalnum())
                    continue

        if body[i] not in _SPACING:
            cascade = False
        out.append(body[i])
        i += 1

    return "".join(out)


# --------------------------------------------------------------------------- #
# 4. empty radicals: \sqrt{} followed by ^ groups
# --------------------------------------------------------------------------- #

RE_EMPTY_SQRT = re.compile(r"\\sqrt\{\}\s*\^\{([^{}]*)\}\s*\^\{([^{}]*)\}")
RE_EMPTY_SQRT1 = re.compile(r"\\sqrt\{\}\s*\^\{([^{}]*)\}")


def fix_empty_sqrt(s: str) -> str:
    s = RE_EMPTY_SQRT.sub(lambda m: f"\\sqrt{{\\frac{{{m.group(1)}}}{{{m.group(2)}}}}}", s)
    s = RE_EMPTY_SQRT1.sub(lambda m: f"\\sqrt{{{m.group(1)}}}", s)
    return s


# --------------------------------------------------------------------------- #
# 5. stacked fractions that lost their bar:  "1 3\ ^{t}^{3}"  ->  \frac{1}{3}t^{3}
# --------------------------------------------------------------------------- #

RE_NUM_STACK = re.compile(
    r"(?<![{\w.])(\d+)\s+(\d+)\s*\\?\s*\^\{([^{}]+)\}")
RE_NUM_STACK_CMD = re.compile(
    r"(?<![{\w.])(\d+)\s+(\d+)\s*\\?\s*(\\[a-zA-Z]+)")


def fix_stacked_fractions(body: str) -> str:
    # "1 3\ ^{t}"  ->  "\frac{1}{3} t"
    body = RE_NUM_STACK.sub(lambda m: rf"\frac{{{m.group(1)}}}{{{m.group(2)}}} {m.group(3)}",
                            body)
    # "1 2\ \sqrt{" -> "\frac{1}{2}\sqrt{"
    body = RE_NUM_STACK_CMD.sub(
        lambda m: rf"\frac{{{m.group(1)}}}{{{m.group(2)}}}\ {m.group(3)}", body)
    return body


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

RE_MATH_RUN = re.compile(r"\$([^$]*)\$")


# --------------------------------------------------------------------------- #
# 6. subscript shape: one letter = quantity (italic), longer = label (upright)
# --------------------------------------------------------------------------- #

RE_SUB_GROUP = re.compile(r"_\{([^{}$\\]*)\}")


def upright_subscripts(body: str) -> str:
    """``a_{avg}`` -> ``a_{\\mathrm{avg}}``; a lone ``v_{x}`` stays italic."""
    def sub(m):
        inner = m.group(1).strip()
        if not inner or "\\" in inner:      # \perp, \circ ... need maths mode
            return m.group(0)
        core = inner.replace(" ", "")
        if len(core) <= 1 or core.isdigit():
            return m.group(0)
        return "_{\\mathrm{" + inner + "}}"
    return RE_SUB_GROUP.sub(sub, body)


def repair(text: str) -> str:
    if not text:
        return text
    s = _fix_backslashes(text)
    # units first: merge_math_runs would otherwise swallow the "$^{2}$" run
    s = pull_units_into_math(s)
    s = fix_stray_bases(s)
    s = merge_math_runs(s)
    s = fix_empty_sqrt(s)

    def fix_run(m):
        body = fix_stacked_fractions(m.group(1))
        body = fix_empty_superscripts(body)
        body = collapse_cascades(body)
        body = upright_subscripts(body)
        return "$" + body + "$"

    s = RE_MATH_RUN.sub(fix_run, s)
    s = tidy_spacing(s)
    s = fix_delimiters(s)
    return s


# --------------------------------------------------------------------------- #
# 4. spacing tidy-up
# --------------------------------------------------------------------------- #

# ``\ \mathrm{m/s}`` -- one spacer is enough before a unit
RE_DOUBLE_SPACE_CMD = re.compile(r"(\\ )\s*\\ (?=\\?[a-zA-Z])")
# ``\mathrm m/s\ `` right before a closing delimiter
RE_TRAIL_SPACE = re.compile(r"\\ \s*(?=[,;.!?)]|\$)")
# In maths an ordinary space renders as nothing, so ``(t - 6) \mathrm{m/s}``
# would print the unit glued to the bracket.  Promote such a space to ``\ ``.
RE_SPACE_BEFORE_UNIT = re.compile(r"(?<=[0-9)\]}])\s+(?=\\mathrm\{)")
# ``\mathrm{m/s} 45^{\circ}`` -- same story on the other side of the unit; the
# lookbehind keeps an existing ``\ `` (backslash + space) from being doubled.
RE_UNIT_BEFORE_NUM = re.compile(
    r"(\\mathrm\{[^{}]*\}(?:\s*\^\{[^{}]*\})?)(?<!\\)[ \t]+(?=[0-9(])")

# A few formulas are stacked so tightly in the source PDF that the extractor can
# only recover a chain of superscripts with no base ("v^{0}^{t}^{cos}").  Real
# TeX refuses those ("Double superscript"), so fold the chain into one exponent.
# the exponent may itself contain braces ("^{\mathrm{L}}"), so match balanced
# groups by scanning rather than with a single flat character class
def _script_group(s: str, i: int) -> tuple[str, int] | None:
    """Read the ``{...}`` or single token starting at ``i``."""
    if i >= len(s):
        return None
    if s[i] != "{":
        m = re.match(r"\\[A-Za-z]+|\S", s[i:])
        return (m.group(0), i + m.end()) if m else None
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return None


def collapse_cascades(s: str) -> str:
    """Fold ``^{a}^{b}`` into ``^{a b}`` so a strict engine accepts the formula."""
    for marker in ("^", "_"):
        changed = True
        while changed:
            changed = False
            out = []
            i = 0
            while i < len(s):
                if s[i] != marker:
                    out.append(s[i])
                    i += 1
                    continue
                first = _script_group(s, i + 1)
                if first is None:
                    out.append(s[i])
                    i += 1
                    continue
                head, after = first
                j = after
                while j < len(s) and s[j] in " \t":
                    j += 1
                if j < len(s) and s[j] == marker:
                    second = _script_group(s, j + 1)
                    if second is not None:
                        tail, after2 = second
                        out.append(marker + "{" + head + " " + tail + "}")
                        i = after2
                        changed = True
                        continue
                out.append(s[i:after])
                i = after
            s = "".join(out)
    return s


# ``_{\sqrt{}}`` / ``^{\mathrm{L}}`` with nothing in front: the base was a
# radical or a fraction whose structure the PDF does not expose.  Drop the empty
# radical and let the exponent stand on its own as an ordinary symbol.
RE_LONE_SQRT = re.compile(r"_\{\\sqrt\{\}\}|\\sqrt\{\}\s*\^")
RE_EMPTY_SCRIPT = re.compile(r"[_^]\{\s*\}")


def clean_orphan_scripts(s: str) -> str:
    out = RE_LONE_SQRT.sub("", s)
    out = RE_EMPTY_SCRIPT.sub("", out)
    return out


# ``$\frac{3}{Evaluate the $\int} ...$`` -- the book stacked a whole sentence
# inside a fraction slot; both the braces and the ``$`` pairs are wrecked.
# Which slice is "right" cannot be recovered, so the run is rewritten into a
# single well-formed formula instead of being thrown away.
# a ``$`` that opens inside a maths run cannot be honoured, so drop it
RE_INNER_OPEN = re.compile(r"\$([^$]*)\$(?=[^$]*\$[^$]*\$)")


def fix_delimiters(s: str) -> str:
    """Balance ``$`` delimiters; a real engine aborts on an odd count."""
    if s.count("$") % 2 == 0:
        return s
    # drop the *last* stray opener: it is the one the PDF swallowed
    idx = s.rfind("$")
    inner = s.rfind("$", 0, idx)
    if inner > 0:
        return s[:inner] + s[inner + 1:]
    return s + "$"


def tidy_spacing(s: str) -> str:
    out = clean_orphan_scripts(s)
    out = RE_SPACE_BEFORE_UNIT.sub(r"\\ ", out)
    out = RE_UNIT_BEFORE_NUM.sub(r"\1\\ ", out)
    out = RE_DOUBLE_SPACE_CMD.sub(r"\1", out)
    out = RE_TRAIL_SPACE.sub("", out)
    return out
