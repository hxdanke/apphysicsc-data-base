"""Authoring a question stem out of blocks.

A stem written by hand in the app is stored as an ordered list of blocks:

* ``{"type": "text",  "text": "..."}``   -- LaTeX, as typed
* ``{"type": "image", "path": "media/x.png", "width": 0.5}``

so the author can interleave prose and figures in any order rather than editing
one long string.

The renderer is untouched: the blocks are flattened into the ordinary ``stem``
LaTeX that every other question already uses, which is why a hand-authored
question composes into a paper exactly like an imported one.  ``stem_blocks`` is
the editable source of truth; ``stem`` is derived from it and kept in sync by
:func:`apply_blocks`.

An image block with no image yet renders as a placeholder figure, so a
half-finished question is visibly incomplete instead of silently missing
something.
"""

from __future__ import annotations

import os
import re

from . import courses as courses_mod

PLACEHOLDER = "media/placeholder.png"
DEFAULT_IMAGE_WIDTH = 0.5
MAX_IMAGE_WIDTH = 1.0

BLOCK_TYPES = ("text", "image")

# anything the extractor may already have written into a stem
_RE_INCLUDEGRAPHICS = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


def _clean_width(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_IMAGE_WIDTH
    if number <= 0:
        return DEFAULT_IMAGE_WIDTH
    return min(number, MAX_IMAGE_WIDTH)


def normalise_blocks(raw) -> list:
    """Coerce whatever the client sent into well-formed blocks."""
    out = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower()
        if kind == "text":
            text = item.get("text")
            out.append({"type": "text", "text": "" if text is None else str(text)})
        elif kind == "image":
            path = str(item.get("path") or "").strip()
            out.append({
                "type": "image",
                "path": path,
                "width": _clean_width(item.get("width")),
                "caption": str(item.get("caption") or "").strip(),
            })
    return out


def image_latex(block: dict) -> str:
    path = str(block.get("path") or "").strip() or PLACEHOLDER
    width = _clean_width(block.get("width"))
    return "\\includegraphics[width=%.2f\\linewidth]{%s}" % (width, path)


def blocks_to_latex(blocks) -> str:
    """Flatten blocks into the stem LaTeX, one paragraph per block."""
    parts = []
    for block in blocks or ():
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            if text:
                parts.append(text)
        elif block.get("type") == "image":
            latex = image_latex(block)
            caption = str(block.get("caption") or "").strip()
            if caption:
                latex += "\n\n" + caption
            parts.append(latex)
    return "\n\n".join(parts)


def blocks_from_question(question: dict) -> list:
    """The editable blocks for a question.

    Questions that arrived from a PDF have no blocks, so their existing stem is
    offered as a single text block -- which is what it is.
    """
    stored = question.get("stem_blocks")
    if stored:
        normalised = normalise_blocks(stored)
        if normalised:
            return normalised
    stem = (question.get("stem") or "").strip()
    if not stem:
        return [{"type": "text", "text": ""}]

    # A stem that is nothing but figures becomes one image block each; mixed
    # content stays a single text block so nothing is silently reinterpreted.
    found = _RE_INCLUDEGRAPHICS.findall(stem)
    stripped = _RE_INCLUDEGRAPHICS.sub("", stem).strip()
    if found and not stripped:
        blocks = []
        for path in found:
            blocks.append({"type": "image", "path": path.strip(),
                           "width": _width_for(stem, path)})
        return blocks
    return [{"type": "text", "text": stem}]


def _width_for(stem: str, path: str) -> float:
    match = re.search(
        r"\\includegraphics\s*\[[^\]]*width\s*=\s*([0-9.]+)\s*\\linewidth[^\]]*\]\s*\{"
        + re.escape(path) + r"\}", stem)
    if match:
        return _clean_width(match.group(1))
    return DEFAULT_IMAGE_WIDTH


def apply_blocks(question: dict, blocks) -> dict:
    """Store the blocks and derive ``stem`` from them, in place."""
    clean = normalise_blocks(blocks)
    question["stem_blocks"] = clean
    question["stem"] = blocks_to_latex(clean)
    return question


def referenced_images(blocks) -> list:
    """Local paths the blocks point at, ignoring the shared placeholder."""
    out = []
    for block in normalise_blocks(blocks):
        if block["type"] != "image":
            continue
        path = block["path"]
        if path and path != PLACEHOLDER:
            out.append(path)
    return out


def store_upload(filename: str, payload: bytes, course_id: str | None = None) -> str:
    """Save an uploaded figure into the shared media store; return its rel path.

    Filenames are prefixed with the course so one store can serve four banks
    without a collision, and the stored name is derived from a hash of the bytes
    so re-uploading the same figure does not pile up copies.
    """
    import hashlib

    suffix = os.path.splitext(filename or "")[1].lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg"}:
        raise ValueError("Unsupported image type: " + (suffix or "unknown"))

    course = courses_mod.get(course_id)
    digest = hashlib.sha256(payload).hexdigest()[:12]
    name = f"{course.id_prefix.lower()}_{digest}{suffix}"
    os.makedirs(courses_mod.MEDIA_DIR, exist_ok=True)
    path = os.path.join(courses_mod.MEDIA_DIR, name)
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(payload)
    return "media/" + name
