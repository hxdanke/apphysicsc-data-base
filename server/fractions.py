"""Geometry-driven rebuilding of stacked fractions and radicals.

The source exercise book *does* draw every fraction bar: it is a thin black
rectangle about 0.72 pt high, and ``\\sqrt{}`` draws the same kind of rectangle as
the horizontal rule over its radicand.  Every structure can therefore be pinned
exactly instead of guessed from baselines:

    numerator      <- its bottom edge sits just above the bar
    ==========     <- the bar, found in ``page.get_drawings()``
    denominator    <- its top edge sits just below the bar

A radical adds one wrinkle: its rule (the vinculum) sits *above* the whole
radicand and hugs the ``v`` glyph on its left.  Anything below the rule inside
that width is the radicand and is rebuilt recursively, so
``\\sqrt{\\frac{g}{3L_0}}`` comes out right.

Everything here is pure geometry and side-effect free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RADICAL_GLYPHS = "\u221a\u221b\u221c"

# A drawn rule counts as a bar when it is thin and short enough to be a fraction
# rule rather than a table border or a figure stroke.  The widest real fraction
# rule in this book is 78 pt (\frac{\sin\theta R+\mu\theta R}{..}); the narrowest
# table border is 93 pt, so 85 pt separates them comfortably.
BAR_H_MIN, BAR_H_MAX = 0.6, 1.6
BAR_W_MIN, BAR_W_MAX = 2.0, 85.0

X_CONTAIN_TOL = 1.5      # how far a term may stick out past its own bar
X_REGION_TOL = 2.0       # slack when defining a recursive region
NUM_WINDOW = 20.0        # how far above the bar a numerator may reach
DEN_WINDOW = 20.0        # how far below the bar a denominator may reach
GAP_TOL = 5.0            # vertical continuity while walking down a radicand
GLYPH_HUG = 2.0          # distance from the "v" glyph to its rule
WINDOW_COMPOUND = 32.0       # how far a nested \frac / \sqrt may reach from the rule
RAD_OVERHANG = 2.0           # a radicand may start this far above its own rule
SCRIPT_TOL = 1.0         # bottom edge offset that marks a sub/superscript
SIZE_RATIO = 0.92          # sub/superscripts are set smaller than the base run
# a bracket or an operator is never a script, so only single letters / digits
# take part in deciding scripts (that is what keeps "[" out of ^{[} )
SCRIPT_CHAR = re.compile(r"^[\w\u0370-\u03ff\u2200-\u22ff]$")
_EPS = 1e-6


@dataclass
class Span:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    flags: int = 0
    size: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Bar:
    x0: float
    x1: float
    y: float
    used: bool = False

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass
class Node:
    """A piece of a page: an untouched span, a fraction, or a radical."""

    kind: str                                   # "atom" | "frac" | "sqrt"
    x0: float
    y0: float
    x1: float
    y1: float
    spans: list = field(default_factory=list)   # atom
    num: list = field(default_factory=list)     # frac
    den: list = field(default_factory=list)     # frac
    body: list = field(default_factory=list)    # sqrt: the radicand
    glyph: Span | None = None                   # sqrt: the "v"
    bar: Bar | None = None                      # frac
    size: float = 0.0                           # font size of the base glyphs
    used: bool = False

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def base_y(self) -> float:
        """The row this piece belongs to, used to file it into a text line."""
        if self.kind == "atom":
            return self.y1
        if self.kind == "frac":
            return self.bar.y
        y = self.glyph.y1 if self.glyph is not None else self.y1
        for c in self.body:
            y = max(y, c.base_y)
        return y

    def leaves(self):
        if self.kind == "atom":
            yield self
            return
        kids = self.body if self.kind == "sqrt" else self.num + self.den
        for c in kids:
            yield from c.leaves()


def _has_ink(node: Node) -> bool:
    """True when the node carries anything but kerning whitespace."""
    return any(lf.spans and lf.spans[0].text.strip() for lf in node.leaves())


def radical_in(text: str) -> bool:
    """True when a span carries a radical sign, wherever it sits in the string."""
    return any(ch in RADICAL_GLYPHS for ch in text)


def collect_bars(page) -> list[Bar]:
    """Every thin rectangle on the page that could be a fraction rule."""
    out: list[Bar] = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                x0, x1 = min(r.x0, r.x1), max(r.x0, r.x1)
                y0, y1 = min(r.y0, r.y1), max(r.y0, r.y1)
            elif it[0] == "l":
                p1, p2 = it[1], it[2]
                x0, x1 = min(p1.x, p2.x), max(p1.x, p2.x)
                y0, y1 = min(p1.y, p2.y), max(p1.y, p2.y)
            else:
                continue
            h, w = y1 - y0, x1 - x0
            if BAR_H_MIN <= h <= BAR_H_MAX and BAR_W_MIN <= w <= BAR_W_MAX:
                out.append(Bar(x0, x1, (y0 + y1) / 2.0))
    return out


class Builder:
    """Turn a flat list of spans into structured nodes."""

    def __init__(self, spans: list[Span], bars: list[Bar]):
        self.spans = spans
        self.bars = bars
        self.nodes: list[Node] = [
            Node("atom", s.x0, s.y0, s.x1, s.y1, spans=[s], size=s.size)
            for s in spans
        ]

    # -- geometry helpers ---------------------------------------------------- #

    @staticmethod
    def _in_x(n: Node, lo: float, hi: float) -> bool:
        return n.x0 >= lo - _EPS and n.x1 <= hi + _EPS

    @staticmethod
    def _in_box(n: Node, lo: float, hi: float, top: float, bot: float) -> bool:
        return (Builder._in_x(n, lo, hi)
                and n.y0 >= top - _EPS and n.y1 <= bot + _EPS)

    def _free(self, lo, hi, top, bot) -> list[Node]:
        return [n for n in self.nodes
                if not n.used and self._in_box(n, lo, hi, top, bot)]

    # -- driver -------------------------------------------------------------- #

    def run(self) -> list[Node]:
        self._resolve(-1e9, 1e9, -1e9, 1e9)
        return [n for n in self.nodes if not n.used]

    def _glyph_for(self, bar: Bar, lo: float, hi: float, bot: float) -> Node | None:
        """The "v" glyph hugging the left end of ``bar``, if ``bar`` is a radical rule."""
        glyph = None
        best = 0.0
        for n in self._free(lo, hi, -1e9, bot):
            if n.kind != "atom" or not n.spans:
                continue
            # The sign sits at the *end* of its span when something else comes
            # first: "\cos(\sqrt{x}t)" arrives as the single span " (\u221a".
            if not (radical_in(n.spans[0].text[-1:])
                    or radical_in(n.spans[0].text[:1])):
                continue
            if abs(n.x1 - bar.x0) > GLYPH_HUG or n.y1 < bar.y - 1.0:
                continue
            # The rule has to sit on top of *this* sign.  Answer grids print their
            # radicals at identical x (Unit 5.2 Q1), so several signs hug the same
            # rule horizontally and the row decides.  A radicand holding a stacked
            # fraction lifts its rule by 13pt or more, so the pair is chosen by
            # distance rather than by a fixed threshold.
            rise = abs(n.y0 - bar.y)
            if glyph is None or rise < best:
                best, glyph = rise, n
        return glyph

    def _resolve(self, lo: float, hi: float, top: float, bot: float) -> None:
        """Resolve every structure inside the box.

        Radical rules always go first, wherever they sit.  A single-digit radical
        such as the one in ``\\frac{v_{max,1}}{\\sqrt{2}}`` keeps its rule *below*
        the surrounding fraction rule, so processing strictly top-down would let
        the fraction swallow the ``2`` before the radical ever existed.
        """
        while True:
            cands = [b for b in self.bars
                     if not b.used and b.x0 >= lo - X_REGION_TOL
                     and b.x1 <= hi + X_REGION_TOL and top - _EPS <= b.y <= bot + _EPS]
            if not cands:
                return
            glyphs = {id(b): self._glyph_for(b, lo, hi, bot) for b in cands}
            radicals = [b for b in cands if glyphs[id(b)] is not None]
            pool = radicals or cands
            bar = min(pool, key=lambda b: b.y)
            if not self._handle(bar, glyphs[id(bar)], bot):
                bar.used = True               # unusable; do not spin on it

    def _handle(self, bar: Bar, glyph: Node | None, bot: float) -> bool:
        if glyph is not None:
            return self._radical(bar, glyph, bot)
        return self._fraction(bar, bot)

    # -- structures ---------------------------------------------------------- #

    def _radical(self, bar: Bar, glyph: Node, hard_bot: float) -> bool:
        lo, hi = glyph.x1 - X_REGION_TOL, bar.x1 + X_REGION_TOL
        bottom = self._continuity_bottom(lo, hi, bar.y, hard_bot, glyph)
        bar.used = True
        glyph.used = True
        top = bar.y - RAD_OVERHANG
        self._resolve(lo, hi, top, bottom)
        kids = sorted(self._free(lo, hi, top, bottom), key=lambda n: n.x0)
        if not kids:
            bar.used = False                  # empty radicand; leave it alone
            glyph.used = False
            return False
        for k in kids:
            k.used = True
        sizes = [lf.size for k in kids for lf in k.leaves()]
        self.nodes.append(Node(
            "sqrt",
            min(glyph.x0, *(k.x0 for k in kids)),
            min(glyph.y0, *(k.y0 for k in kids)),
            max(bar.x1, *(k.x1 for k in kids)),
            max(glyph.y1, *(k.y1 for k in kids)),
            body=kids, glyph=glyph.spans[0], size=max(sizes) if sizes else 0.0,
        ))
        return True

    def _continuity_bottom(self, lo: float, hi: float, top: float,
                           hard_bot: float, glyph: Node) -> float:
        """How far down a radicand reaches.

        Everything below the rule belongs to it while the pieces keep touching,
        so walking down and stopping at the first vertical gap finds the bottom
        without ever looking at what comes afterwards.
        """
        cands = [n for n in self.nodes
                 if not n.used and n.kind == "atom" and n is not glyph
                 and n.x0 >= lo - _EPS and n.x1 <= hi + _EPS
                 and n.y0 >= top - RAD_OVERHANG and n.y0 <= hard_bot + _EPS]
        cands.sort(key=lambda n: (n.y0, n.x0))
        if not cands:
            return top
        low = cands[0].y1
        for n in cands[1:]:
            if n.y0 > low + GAP_TOL:
                break
            low = max(low, n.y1)
        return low

    def _fraction(self, bar: Bar, bot: float) -> bool:
        lo, hi = bar.x0 - X_CONTAIN_TOL, bar.x1 + X_CONTAIN_TOL
        # Anything nested inside this fraction has to be built first: its own
        # numerator sits above the rule and would otherwise be collected raw,
        # which is how "[I_1 + I_2 (r_1/r_2)]" used to come out as "[I1+I2 (r12)]".
        bar.used = True
        self._resolve(lo, hi, bar.y - NUM_WINDOW, bar.y + 0.2)
        self._resolve(lo, hi, bar.y - 0.2, bar.y + DEN_WINDOW)

        def window(node: Node) -> tuple[float, float]:
            # A compound node belongs to its own expression, so it may reach
            # further from the rule than a plain glyph run; widening it lets a
            # nested fraction sit inside a denominator.  Atoms keep the tight
            # window: that is what stops the *next* answer row from being read
            # as this row's denominator.
            reach = WINDOW_COMPOUND if node.kind != "atom" else max(NUM_WINDOW, DEN_WINDOW)
            return bar.y - reach, bar.y + reach

        def select(above: bool) -> list[Node]:
            out = []
            for n in self.nodes:
                if n.used:
                    continue
                if not _has_ink(n):
                    continue
                # glyphs must stay inside the rule's width so that no wide line
                # of prose can ever become a numerator
                if not self._in_x(n, lo, hi):
                    continue
                low, top_ = window(n)
                if n.y0 < low - _EPS or n.y1 > top_ + _EPS:
                    continue
                near = n.y1 if above else n.y0
                far = n.y0 if above else n.y1
                if above and not (bar.y - NUM_WINDOW <= near <= bar.y + 0.2):
                    continue
                if not above and not (bar.y - 0.2 <= near <= bar.y + DEN_WINDOW):
                    continue
                if above and far < low - _EPS:
                    continue
                if not above and far > top_ + _EPS:
                    continue
                out.append(n)
            return out

        num, den = select(True), select(False)
        if not num or not den:
            return False
        for n in num + den:
            n.used = True
        num.sort(key=lambda n: n.x0)
        den.sort(key=lambda n: n.x0)
        sizes = [lf.size for n in num + den for lf in n.leaves()]
        self.nodes.append(Node(
            "frac",
            min(min(n.x0 for n in num), min(n.x0 for n in den), bar.x0),
            min(n.y0 for n in num),
            max(max(n.x1 for n in num), max(n.x1 for n in den), bar.x1),
            max(n.y1 for n in den),
            num=num, den=den, bar=bar, size=max(sizes) if sizes else 0.0,
        ))
        return True


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def _baseline_voter(text: str) -> bool:
    """True when a full-size span sits on a normal text baseline.

    Only letters, digits, Greek and maths symbols qualify, so a bracket --
    whose box overhangs the baseline at both ends -- cannot hijack the vote.
    Multi-character spans qualify too, otherwise a run made of nothing but
    "dt" leaves the row without any reference and its script is dropped.
    """
    t = text.strip()
    return bool(t) and all(SCRIPT_CHAR.match(ch) for ch in t)


def _scripts_of(nodes: list[Node]) -> dict[int, str]:
    """Map node id -> "^" or "_" for every member of the run that is a script.

    A fraction's row has no surrounding text to lean on, so the baseline comes
    from the glyphs printed at full size: whatever is markedly smaller is a
    script, and whether it rises or falls decides "^" or "_".  Brackets and
    operators never take part -- taking the tallest box as the reference would
    otherwise make "[" a superscript and turn everything else upside down.
    Ordinary runs count even when several letters share one span ("dt^2").
    """
    atoms = [n for n in nodes if n.kind == "atom" and n.spans]
    if len(atoms) < 2:
        return {}
    sizes = [n.size for n in atoms]
    base = max(sizes)
    same = [n.y1 for n in atoms
            if n.size >= base * SIZE_RATIO and _baseline_voter(n.spans[0].text)]
    counts: dict[float, int] = {}
    for y in same:
        k = round(y)
        counts[k] = counts.get(k, 0) + 1
    if not counts:
        return {}
    ref = max(counts, key=lambda k: counts[k])
    out = {}
    for n in atoms:
        if n.size >= base * SIZE_RATIO:
            continue
        text = n.spans[0].text
        if not text.strip():                 # stray kerning space
            continue
        if n.y1 < ref - SCRIPT_TOL:
            out[id(n)] = "^"
        elif n.y1 > ref + SCRIPT_TOL:
            out[id(n)] = "_"
    return out


def node_latex(node: Node, conv) -> str:
    """LaTeX body (no delimiters) for one node.  ``conv`` maps raw text -> LaTeX."""
    if node.kind == "frac":
        return (r"\frac{" + run_latex(node.num, conv) + "}{"
                + run_latex(node.den, conv) + "}")
    if node.kind == "sqrt":
        return r"\sqrt{" + run_latex(node.body, conv) + "}"
    if node.spans:
        return conv(node.spans[0].text)
    return ""


def run_latex(nodes: list[Node], conv) -> str:
    """LaTeX for a run of nodes on one level -- a numerator or a radicand."""
    marks = _scripts_of(nodes)
    pieces = []
    for n in nodes:
        body = node_latex(n, conv)
        m = marks.get(id(n))
        pieces.append(m + "{" + body.strip() + "}" if m else body)
    return "".join(pieces)
