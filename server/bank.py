"""Question-bank storage, one bank per course.

Each course keeps its own JSON bank (git friendly, diffable, no database to
migrate).  ``data/media/`` holds the figures the LaTeX bodies reference with
``\\includegraphics`` and is shared between courses; filenames carry the course
they came from.

Every function takes a ``course_id`` and defaults to AP Physics C: Mechanics,
which is what the pre-multi-course scripts expect -- they keep working untouched.

Beyond the unit/topic a question is filed under, a question may carry
``additional_topics``: the other knowledge blocks it draws on.  A mechanics
question that is really about energy *and* momentum can be found from either
side, and filtering by a topic matches questions that list it as primary *or* as
additional.
"""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy

from . import courses as courses_mod

ROOT = courses_mod.ROOT
DATA_DIR = courses_mod.DATA_DIR
MEDIA_DIR = courses_mod.MEDIA_DIR
# Absolute paths for the default course, kept for the pre-multi-course scripts
# that reach for these constants directly.
BANK_PATH = courses_mod.get(None).path(courses_mod.get(None).bank)
TAXONOMY_PATH = courses_mod.get(None).path(courses_mod.get(None).taxonomy)
EXPORT_DIR = os.path.join(ROOT, "exports")

_lock = threading.Lock()

# --------------------------------------------------------------------------------------
# taxonomy
# --------------------------------------------------------------------------------------

DEFAULT_TAXONOMY = {
    "course": "AP Physics C: Mechanics",
    "units": [
        {"id": 1, "title": "Kinematics", "topics": [
            {"id": "1.1", "title": "Scalars and Vectors"},
            {"id": "1.2", "title": "Displacement, Velocity, and Acceleration"},
            {"id": "1.3", "title": "Representing Motion"},
            {"id": "1.4", "title": "Reference Frames and Relative Motion"},
            {"id": "1.5", "title": "Motion in Two or Three Dimensions"},
        ]},
        {"id": 2, "title": "Force and Translational Dynamics", "topics": [
            {"id": "2.1", "title": "Systems and Center of Mass"},
            {"id": "2.2", "title": "Forces and Free-Body Diagrams"},
            {"id": "2.3", "title": "Newton's Third Law"},
            {"id": "2.4", "title": "Newton's First Law"},
            {"id": "2.5", "title": "Newton's Second Law"},
            {"id": "2.6", "title": "Gravitational Force"},
            {"id": "2.7", "title": "Kinetic and Static Friction"},
            {"id": "2.8", "title": "Spring Forces"},
            {"id": "2.9", "title": "Resistive Forces"},
            {"id": "2.10", "title": "Circular Motion"},
        ]},
        {"id": 3, "title": "Work, Energy, and Power", "topics": [
            {"id": "3.1", "title": "Translational Kinetic Energy"},
            {"id": "3.2", "title": "Work"},
            {"id": "3.3", "title": "Potential Energy"},
            {"id": "3.4", "title": "Conservation of Energy"},
            {"id": "3.5", "title": "Power"},
        ]},
        {"id": 4, "title": "Linear Momentum", "topics": [
            {"id": "4.1", "title": "Linear Momentum"},
            {"id": "4.2", "title": "Change in Momentum and Impulse"},
            {"id": "4.3", "title": "Conservation of Linear Momentum"},
            {"id": "4.4", "title": "Elastic and Inelastic Collisions"},
        ]},
        {"id": 5, "title": "Torque and Rotational Dynamics", "topics": [
            {"id": "5.1", "title": "Rotational Kinematics"},
            {"id": "5.2", "title": "Connecting Linear and Rotational Motion"},
            {"id": "5.3", "title": "Torque"},
            {"id": "5.4", "title": "Rotational Inertia"},
            {"id": "5.5", "title": "Rotational Equilibrium and Newton's First Law in Rotational Form"},
            {"id": "5.6", "title": "Newton's Second Law in Rotational Form"},
        ]},
        {"id": 6, "title": "Energy and Momentum of Rotating Systems", "topics": [
            {"id": "6.1", "title": "Rotational Kinetic Energy"},
            {"id": "6.2", "title": "Torque and Work"},
            {"id": "6.3", "title": "Angular Momentum and Angular Impulse"},
            {"id": "6.4", "title": "Conservation of Angular Momentum"},
            {"id": "6.5", "title": "Rolling"},
            {"id": "6.6", "title": "Motion of Orbiting Satellites"},
        ]},
        {"id": 7, "title": "Oscillations", "topics": [
            {"id": "7.1", "title": "Defining Simple Harmonic Motion (SHM)"},
            {"id": "7.2", "title": "Frequency and Period of SHM"},
            {"id": "7.3", "title": "Representing and Analyzing SHM"},
            {"id": "7.4", "title": "Energy of Simple Harmonic Oscillators"},
            {"id": "7.5", "title": "Simple and Physical Pendulums"},
        ]},
    ],
}


def load_taxonomy(course_id: str | None = None) -> dict:
    course = courses_mod.get(course_id)
    path = course.path(course.taxonomy)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Only the default course has a fallback; a new course must ship its own.
    return deepcopy(DEFAULT_TAXONOMY)


def save_taxonomy(tax: dict, course_id: str | None = None) -> None:
    course = courses_mod.get(course_id)
    path = course.path(course.taxonomy)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tax, f, ensure_ascii=False, indent=2)


def resolve_topic(topic_id: str, course_id: str | None = None) -> tuple:
    """Return ``(unit_id, topic_title)`` for a topic id, or ``(0, "")``."""
    for unit in load_taxonomy(course_id).get("units", []):
        for topic in unit.get("topics", []):
            if str(topic["id"]) == str(topic_id):
                return unit["id"], topic["title"]
    return 0, ""


def topic_titles(course_id: str | None = None) -> dict:
    """Every ``unit|topic`` id mapped to its title."""
    return {
        f"{unit['id']}|{topic['id']}": topic["title"]
        for unit in load_taxonomy(course_id).get("units", [])
        for topic in unit.get("topics", [])
    }


# --------------------------------------------------------------------------------------
# bank
# --------------------------------------------------------------------------------------

def blank_question(qid: str, unit: int = 0, topic: str = "") -> dict:
    return {
        "id": qid, "unit": unit, "unit_title": "", "topic": topic, "topic_title": "",
        "number": 0, "qtype": "mcq", "stem": "", "choices": [], "answer": "",
        "solution": "", "images": [], "difficulty": "", "tags": [],
        "source": {}, "layout": "inline", "needs_review": False,
        "stem_blocks": [], "additional_topics": [],
    }


def load_bank(course_id: str | None = None) -> dict:
    course = courses_mod.get(course_id)
    path = course.path(course.bank)
    if not os.path.exists(path):
        return {"version": 1, "course": course.title, "questions": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bank(bank: dict, course_id: str | None = None) -> None:
    course = courses_mod.get(course_id)
    path = course.path(course.bank)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def next_id(bank: dict, unit: int, topic: str, course_id: str | None = None) -> str:
    course = courses_mod.get(course_id)
    used = {q["id"] for q in bank["questions"]}
    prefix = f"{course.id_prefix}-U{unit}-{topic or '0'}-Q"
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def upsert(bank: dict, questions: list, replace_source: str | None = None,
           course_id: str | None = None) -> int:
    """Insert or replace questions and write the bank.  Returns how many were written."""
    with _lock:
        if replace_source:
            bank["questions"] = [q for q in bank["questions"]
                                 if (q.get("source") or {}).get("doc") != replace_source]
        index = {q["id"]: i for i, q in enumerate(bank["questions"])}
        for q in questions:
            if q["id"] in index:
                bank["questions"][index[q["id"]]] = q
            else:
                bank["questions"].append(q)
        save_bank(bank, course_id)
    return len(questions)


def delete_question(bank: dict, qid: str, course_id: str | None = None) -> bool:
    """Remove a question and write the bank.  True when something was removed."""
    before = len(bank["questions"])
    bank["questions"] = [q for q in bank["questions"] if q["id"] != qid]
    if len(bank["questions"]) == before:
        return False
    save_bank(bank, course_id)
    return True


def stats(bank: dict) -> dict:
    qs = bank["questions"]
    per_topic: dict = {}
    for q in qs:
        key = f"{q.get('unit', 0)}|{q.get('topic', '')}"
        per_topic[key] = per_topic.get(key, 0) + 1
    return {
        "total": len(qs),
        "with_answer": sum(1 for q in qs if q.get("answer")),
        "with_solution": sum(1 for q in qs if (q.get("solution") or "").strip()),
        "needs_review": sum(1 for q in qs if q.get("needs_review")),
        "images": sum(len(q.get("images") or []) for q in qs),
        "per_topic": per_topic,
        "units": sorted({q.get("unit", 0) for q in qs}),
    }


# --------------------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------------------

_IMG = re.compile(r"\\includegraphics\[[^\]]*\]\{[^{}]*\}")


def plain_text(q: dict) -> str:
    """Question text with all LaTeX markup stripped - used by the search box."""
    s = q.get("stem", "") + " " + " ".join(c.get("text", "") for c in q.get("choices", []))
    s = _IMG.sub(" ", s)
    s = re.sub(r"\$[^$]*\$", lambda m: re.sub(r"[\\{}$\s]", " ", m.group(0)), s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


MAX_TAG_LENGTH = 40
MAX_TAGS_PER_QUESTION = 12


def clean_tags(values) -> list[str]:
    """Normalise a tag list: trimmed, de-duplicated, bounded.

    Duplicates are compared case-insensitively but the first spelling wins, so
    "Forces" and "forces" cannot both end up on the same question while the
    capitalisation the teacher typed is preserved.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        text = str(raw).strip()
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            text = text[:MAX_TAG_LENGTH].strip()
            if not text:
                continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= MAX_TAGS_PER_QUESTION:
            break
    return out


def tag_counts(bank: dict) -> dict[str, int]:
    """Every tag in this bank with how many questions carry it."""
    counts: dict[str, int] = {}
    for question in bank["questions"]:
        for tag in clean_tags(question.get("tags")):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def topics_of(q: dict) -> list[str]:
    """Every knowledge block a question is filed under, primary first."""
    out = []
    primary = q.get("topic")
    if primary:
        out.append(str(primary))
    for extra in q.get("additional_topics") or []:
        text = str(extra)
        if text and text not in out:
            out.append(text)
    return out


def units_of(q: dict, course_id: str | None = None) -> set:
    """The unit ids a question touches, from its primary and additional topics."""
    out = set()
    if q.get("unit") is not None:
        out.add(q.get("unit"))
    for topic in q.get("additional_topics") or []:
        unit, _ = resolve_topic(str(topic), course_id)
        if unit:
            out.add(unit)
    return out


def search(bank: dict, query: str = "", unit: int | None = None, topic: str | None = None,
           qtype: str | None = None, needs_review: bool | None = None,
           untagged: bool | None = None, limit: int = 500,
           course_id: str | None = None) -> list:
    q = (query or "").strip().lower()
    out = []
    for item in bank["questions"]:
        if unit is not None and unit not in units_of(item, course_id):
            continue
        # A topic filter matches the primary topic *or* any additional one.
        if topic and str(topic) not in topics_of(item):
            continue
        if qtype and item.get("qtype") != qtype:
            continue
        if needs_review is True and not item.get("needs_review"):
            continue
        if untagged is True and (item.get("difficulty") or item.get("tags")):
            continue
        if q:
            hay = plain_text(item) + " " + (item.get("id", "")).lower() \
                  + " " + " ".join(t.lower() for t in item.get("tags", []))
            if all(tok in hay for tok in q.split()):
                out.append(item)
        else:
            out.append(item)
        if len(out) >= limit:
            break
    return out
