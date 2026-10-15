"""The courses this installation serves, and where each one keeps its data.

Banks are deliberately separate files: a question in AP Physics 1 is not visible
to someone building an AP Physics C paper, and composing a paper never reaches
across courses.  Everything that touches the bank -- browse, search, compose,
export, the recycle bin -- is therefore addressed by course id.

Two deliberate choices keep this simple:

* **Figures live in one shared store** (``data/media``) with course-prefixed
  filenames.  The bank is what must not mix; a PNG is just an asset, and one
  store means the LaTeX preamble's ``\\graphicspath`` never has to change.
* **AP Physics C: Mechanics keeps its original paths** (``data/bank.json``,
  ``data/taxonomy.json``).  It predates the multi-course layout, and moving 369
  questions to make the directory tree tidier would risk them for no gain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The data root can be relocated, which is how the test suite runs against a
# throw-away bank tree instead of the real one.  Course paths below are relative
# to it.
DATA_DIR = os.environ.get("QB_DATA_DIR") or os.path.join(ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
BANKS_DIR = os.path.join(DATA_DIR, "banks")


@dataclass(frozen=True)
class Course:
    id: str
    title: str          # full name, shown in the course switcher
    short: str          # compact label for badges
    bank: str           # question bank, relative to DATA_DIR
    taxonomy: str       # unit / topic tree, relative to DATA_DIR
    recycled: str       # recycle bin, relative to DATA_DIR
    id_prefix: str      # prefix for newly authored question ids

    def path(self, relative: str) -> str:
        return os.path.join(DATA_DIR, relative)


COURSES: dict[str, Course] = {
    "apc-mech": Course(
        id="apc-mech",
        title="AP Physics C: Mechanics",
        short="AP C Mech",
        bank="bank.json",
        taxonomy="taxonomy.json",
        recycled="recycled.json",
        id_prefix="APCM",
    ),
    "apc-em": Course(
        id="apc-em",
        title="AP Physics C: Electricity and Magnetism",
        short="AP C E&M",
        bank="banks/apc-em/bank.json",
        taxonomy="banks/apc-em/taxonomy.json",
        recycled="banks/apc-em/recycled.json",
        id_prefix="APCE",
    ),
    "ap1": Course(
        id="ap1",
        title="AP Physics 1",
        short="AP Physics 1",
        bank="banks/ap1/bank.json",
        taxonomy="banks/ap1/taxonomy.json",
        recycled="banks/ap1/recycled.json",
        id_prefix="AP1",
    ),
    "ap2": Course(
        id="ap2",
        title="AP Physics 2",
        short="AP Physics 2",
        bank="banks/ap2/bank.json",
        taxonomy="banks/ap2/taxonomy.json",
        recycled="banks/ap2/recycled.json",
        id_prefix="AP2",
    ),
}

DEFAULT_COURSE_ID = "apc-mech"

# The course ids in the order they should appear in the switcher.
COURSE_ORDER = ["apc-mech", "apc-em", "ap1", "ap2"]


def all_courses() -> list[Course]:
    return [COURSES[cid] for cid in COURSE_ORDER]


def get(course_id: str | None) -> Course:
    """Look up a course, falling back to the default for absent/unknown ids."""
    if course_id and course_id in COURSES:
        return COURSES[course_id]
    return COURSES[DEFAULT_COURSE_ID]


def known(course_id: str | None) -> bool:
    return bool(course_id) and course_id in COURSES


def bank_path(course_id: str | None) -> str:
    return get(course_id).path(get(course_id).bank)


def taxonomy_path(course_id: str | None) -> str:
    return get(course_id).path(get(course_id).taxonomy)


def recycled_path(course_id: str | None) -> str:
    return get(course_id).path(get(course_id).recycled)


def summary() -> list[dict]:
    """What the switcher needs: id, label and how many questions each has."""
    from . import bank as bank_mod  # local import: bank imports this module

    out = []
    for course in all_courses():
        data = bank_mod.load_bank(course.id)
        out.append({
            "id": course.id,
            "title": course.title,
            "short": course.short,
            "questions": len(data.get("questions") or []),
        })
    return out
