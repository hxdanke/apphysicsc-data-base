"""The question recycle bin.

Deleting a question does not destroy it.  It moves out of the bank and into a
per-course recycle bin, keeping the whole question object plus who removed it and
when.  From there it can be restored, deleted for good by hand, or -- if nobody
touches it -- it is dropped automatically once it has been in the bin for
:data:`RETENTION_DAYS` days.

The retention window is enforced lazily: every entry point sweeps expired items
first and writes the result back, so the bin self-cleans without a scheduled job
and without the answer depending on when the server last ran.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from . import bank as bank_mod
from . import courses as courses_mod

RETENTION_DAYS = 30

# Shanghai time, matching the app database's convention.
TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(TZ)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _parse(text: str) -> datetime | None:
    try:
        parsed = datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=TZ)


def _path(course_id: str | None) -> str:
    course = courses_mod.get(course_id)
    return course.path(course.recycled)


def load(course_id: str | None = None) -> dict:
    path = _path(course_id)
    if not os.path.exists(path):
        return {"version": 1, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {"version": 1, "items": []}
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def save(data: dict, course_id: str | None = None) -> None:
    path = _path(course_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def purge_expired(data: dict) -> tuple[dict, list]:
    """Drop everything past its retention window.  Returns (data, removed)."""
    cutoff = _now() - timedelta(days=RETENTION_DAYS)
    kept, removed = [], []
    for item in data.get("items", []):
        deleted_at = _parse(item.get("deleted_at"))
        # An unparseable timestamp is treated as brand new rather than deleted,
        # so a corrupt row can never silently destroy a question.
        if deleted_at is not None and deleted_at < cutoff:
            removed.append(item)
        else:
            kept.append(item)
    data["items"] = kept
    return data, removed


def sweep(course_id: str | None = None) -> list:
    """Run the retention sweep and persist it.  Returns what was purged."""
    data = load(course_id)
    data, removed = purge_expired(data)
    if removed:
        save(data, course_id)
    return removed


def _expiry(deleted_at: str) -> str | None:
    moment = _parse(deleted_at)
    if moment is None:
        return None
    return _stamp(moment + timedelta(days=RETENTION_DAYS))


def describe(item: dict) -> dict:
    """A bin row as the UI needs it: what it is, when it goes for good."""
    question = item.get("question") or {}
    return {
        "id": question.get("id"),
        "unit": question.get("unit"),
        "unit_title": question.get("unit_title"),
        "topic": question.get("topic"),
        "topic_title": question.get("topic_title"),
        "additional_topics": question.get("additional_topics") or [],
        "number": question.get("number"),
        "qtype": question.get("qtype"),
        "preview": _preview(question),
        "deleted_at": item.get("deleted_at"),
        "deleted_by": item.get("deleted_by"),
        "deleted_by_name": item.get("deleted_by_name"),
        "expires_at": _expiry(item.get("deleted_at")),
        "days_left": _days_left(item.get("deleted_at")),
        "question": question,
    }


def _preview(question: dict) -> str:
    text = bank_mod.plain_text(question)
    return text[:160]


def _days_left(deleted_at: str) -> int | None:
    moment = _parse(deleted_at)
    if moment is None:
        return None
    remaining = (moment + timedelta(days=RETENTION_DAYS)) - _now()
    return max(0, remaining.days + (1 if remaining.seconds else 0))


def list_items(course_id: str | None = None) -> list:
    sweep(course_id)
    data = load(course_id)
    items = [describe(item) for item in data.get("items", [])]
    items.sort(key=lambda row: row.get("deleted_at") or "", reverse=True)
    return items


def move_to_bin(question: dict, course_id: str | None = None,
                user: dict | None = None) -> dict:
    """Put a question in the bin.  The caller removes it from the bank."""
    sweep(course_id)
    data = load(course_id)
    data["items"] = [item for item in data.get("items", [])
                     if (item.get("question") or {}).get("id") != question.get("id")]
    entry = {
        "question": question,
        "deleted_at": _stamp(),
        "deleted_by": (user or {}).get("id"),
        "deleted_by_name": (user or {}).get("display_name") or (user or {}).get("username"),
    }
    data["items"].append(entry)
    save(data, course_id)
    return describe(entry)


def find(course_id: str | None, question_id: str) -> dict | None:
    for item in load(course_id).get("items", []):
        if (item.get("question") or {}).get("id") == question_id:
            return item
    return None


def restore(question_id: str, course_id: str | None = None) -> dict | None:
    """Put a binned question back in the bank.  Returns the question, or None."""
    sweep(course_id)
    data = load(course_id)
    entry = None
    rest = []
    for item in data.get("items", []):
        if (item.get("question") or {}).get("id") == question_id and entry is None:
            entry = item
        else:
            rest.append(item)
    if entry is None:
        return None

    question = entry.get("question") or {}
    bank = bank_mod.load_bank(course_id)
    if any(q.get("id") == question.get("id") for q in bank["questions"]):
        # Already back in the bank (restored twice, or edited in); just drop it.
        data["items"] = rest
        save(data, course_id)
        return question
    bank["questions"].append(question)
    bank_mod.save_bank(bank, course_id)

    data["items"] = rest
    save(data, course_id)
    return question


def purge(question_id: str, course_id: str | None = None) -> bool:
    """Delete one binned question for good."""
    data = load(course_id)
    before = len(data.get("items", []))
    data["items"] = [item for item in data.get("items", [])
                     if (item.get("question") or {}).get("id") != question_id]
    if len(data["items"]) == before:
        return False
    save(data, course_id)
    return True


def empty(course_id: str | None = None) -> int:
    """Delete everything in the bin for good."""
    data = load(course_id)
    count = len(data.get("items", []))
    data["items"] = []
    save(data, course_id)
    return count
