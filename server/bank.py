"""Question-bank storage.

The bank is plain JSON on disk (git friendly, diffable, no database to migrate).
`data/bank.json` holds every question; `data/media/` holds the figures that the
LaTeX bodies reference with \\includegraphics.
"""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
BANK_PATH = os.path.join(DATA_DIR, "bank.json")
TAXONOMY_PATH = os.path.join(DATA_DIR, "taxonomy.json")
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


def load_taxonomy() -> dict:
    if os.path.exists(TAXONOMY_PATH):
        with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return deepcopy(DEFAULT_TAXONOMY)


def save_taxonomy(tax: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(tax, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------------------
# bank
# --------------------------------------------------------------------------------------

def blank_question(qid: str) -> dict:
    return {
        "id": qid, "unit": 0, "unit_title": "", "topic": "", "topic_title": "",
        "number": 0, "qtype": "mcq", "stem": "", "choices": [], "answer": "",
        "solution": "", "images": [], "difficulty": "", "tags": [],
        "source": {}, "layout": "inline", "needs_review": False,
    }


def load_bank() -> dict:
    if not os.path.exists(BANK_PATH):
        return {"version": 1, "course": "AP Physics C: Mechanics", "questions": []}
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bank(bank: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = BANK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BANK_PATH)


def next_id(bank: dict, unit: int, topic: str) -> str:
    used = {q["id"] for q in bank["questions"]}
    prefix = f"Q-U{unit}-{topic or '0'}-"
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def upsert(bank: dict, questions: list, replace_source: str | None = None) -> int:
    """Insert or replace questions.  Returns how many were written."""
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
        save_bank(bank)
    return len(questions)


def delete_question(bank: dict, qid: str) -> bool:
    before = len(bank["questions"])
    bank["questions"] = [q for q in bank["questions"] if q["id"] != qid]
    if len(bank["questions"]) != before:
        save_bank(bank)
        return True
    return False


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


def search(bank: dict, query: str = "", unit: int | None = None, topic: str | None = None,
           qtype: str | None = None, needs_review: bool | None = None,
           untagged: bool | None = None, limit: int = 500) -> list:
    q = (query or "").strip().lower()
    out = []
    for item in bank["questions"]:
        if unit is not None and item.get("unit") != unit:
            continue
        if topic and item.get("topic") != topic:
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
