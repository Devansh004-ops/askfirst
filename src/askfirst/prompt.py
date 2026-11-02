"""Prompt construction shared by all model-backed providers."""
from __future__ import annotations

from askfirst.model import SQLRequest

SYSTEM = """You write SQLite queries that answer questions about the database described below.

Rules:
- Reply with ONE read-only SELECT statement (a WITH ... SELECT is fine) and nothing else:
  no markdown fences, no comments, no explanation.
- Use only the tables and columns listed. Never invent a column.
- Where a value list is shown, spell values exactly as listed.
- Dates are ISO text (YYYY-MM-DD). Measure every relative phrase ("last 30 days", "this year")
  from the TODAY value given below, written as a literal, e.g. date('2026-01-15', '-30 day').
  Never use 'now' or date('now').
- "Interpretations" below are the user's own decisions about vague words. Follow them exactly.
- Return only the columns the question asks for, plus an identifying column when ranking."""


def build_user_prompt(req: SQLRequest) -> str:
    parts = [f"TODAY: {req.today}", "", "SCHEMA:", req.schema]
    if req.notes:
        parts += ["", "NOTES:"] + [f"- {n}" for n in req.notes]
    if req.resolutions:
        parts += ["", "INTERPRETATIONS:"] + [f'- "{r.term}": {r.interpretation.hint}' for r in req.resolutions]
    parts += ["", f"QUESTION: {req.question}"]
    if req.previous_sql and req.error:
        parts += ["", "Your previous attempt failed. Return a corrected query.",
                  f"PREVIOUS SQL:\n{req.previous_sql}", f"SQLITE ERROR:\n{req.error}"]
    return "\n".join(parts)


def strip_code_fence(text: str, languages: tuple = ()) -> str:
    """Return what sits inside the first ``` fence of `text` (or `text` itself if there is none).

    An opening language tag is dropped only if it is one of `languages`, so
    "```json" loses its tag but a one-line "```SELECT 1```" keeps its content.
    """
    text = (text or "").strip()
    opening = text.find("```")
    if opening < 0:
        return text
    inside = text[opening + 3:]
    closing = inside.find("```")
    if closing >= 0:
        inside = inside[:closing]
    tag, newline, remainder = inside.partition("\n")
    if newline and tag.strip().lower() in {"", *(lang.lower() for lang in languages)}:
        inside = remainder
    return inside.strip()


def extract_sql(text: str) -> str:
    """The SQL in a model reply, whether or not the model wrapped it in a markdown fence."""
    return strip_code_fence(text, ("sql", "sqlite", "postgresql"))
