"""
Optional AI polish step for the ingestion pipeline.

The deterministic extractor (server/extract.py) produces a structurally correct but
typographically rough draft.  This module hands each draft question to an
OpenAI-compatible chat endpoint and asks for clean LaTeX back.  It is entirely optional:
without an API key the pipeline simply keeps the draft.

Configuration (environment variables or .env next to the repo root):
    AI_API_KEY       - required, otherwise the step is skipped
    AI_BASE_URL      - default https://api.openai.com/v1
    AI_MODEL         - default gpt-4o-mini
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

SYSTEM_PROMPT = """You are a LaTeX typesetting expert for AP Physics C: Mechanics.

You receive a question that was extracted from a PDF. Fix it and return STRICT JSON:
{
  "stem": "...",            // LaTeX, images kept as \\includegraphics[width=..\\linewidth]{media/..}
  "choices": [{"label":"A","text":"..."}],
  "answer": "",             // leave "" if unknown
  "solution": "",           // leave "" if unknown
  "topic": "",              // e.g. "2.5" - keep the value you were given unless clearly wrong
  "difficulty": "",         // easy | medium | hard, or ""
  "tags": []
}

Rules
- Keep every \\includegraphics token EXACTLY as given, including the path.
- Use inline $...$ for math, display \\[ ... \\] only for stand-alone equations.
- Units upright: \\mathrm{m/s^2}. Vectors \\vec{v}. Unit vectors \\hat{i}.
- Repair broken sub/superscripts, stacked fractions (\\frac{}{}), radicals (\\sqrt{}).
- Do NOT invent an answer or a solution. Leave them empty when unknown.
- Do not add commentary. Output JSON only.
"""


def config() -> dict:
    return {
        "api_key": os.environ.get("AI_API_KEY", "").strip(),
        "base_url": os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.environ.get("AI_MODEL", "gpt-4o-mini"),
    }


def enabled() -> bool:
    return bool(config()["api_key"])


def _call(messages: list, temperature: float = 0.0) -> str:
    cfg = config()
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


_JSON = re.compile(r"\{.*\}", re.S)


def polish_question(q: dict) -> dict:
    """Return a polished copy of `q`; falls back to the input on any failure."""
    if not enabled():
        return q
    user = json.dumps({
        "id": q.get("id"),
        "topic": q.get("topic"),
        "stem": q.get("stem"),
        "choices": q.get("choices"),
    }, ensure_ascii=False)
    try:
        raw = _call([{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}])
        m = _JSON.search(raw)
        data = json.loads(m.group(0)) if m else json.loads(raw)
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
        q = dict(q)
        q["ai_error"] = str(exc)
        return q

    out = dict(q)
    out["stem"] = data.get("stem") or q.get("stem")
    ch = data.get("choices")
    if isinstance(ch, list) and ch:
        out["choices"] = [{"label": c.get("label", chr(65 + i)), "text": c.get("text", "")}
                          for i, c in enumerate(ch)]
    for key in ("answer", "solution", "difficulty"):
        if data.get(key):
            out[key] = data[key]
    if data.get("topic"):
        out["topic"] = data["topic"]
    if data.get("tags"):
        out["tags"] = data["tags"]
    out["needs_review"] = False
    out["ai_polished"] = True
    return out


def polish_batch(questions: list, limit: int | None = None) -> list:
    if not enabled():
        return questions
    out = []
    for i, q in enumerate(questions):
        if limit is not None and i >= limit:
            out.append(q)
            continue
        out.append(polish_question(q))
    return out
