"""Gemini-backed provider (needs `pip install askfirst[gemini]` and GEMINI_API_KEY)."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from askfirst.model import Interpretation, Rule, SQLRequest
from askfirst.prompt import SYSTEM, build_user_prompt, extract_sql, strip_code_fence

PROBE_PROMPT = """You review a question about a database for vague words whose meaning would change the SQL
(a ranking word like "best", a metric like "sales", a time word like "recent").
If there is one, reply with JSON only:
{{"term": str, "question": str, "options": [{{"label": str, "hint": str}}, ...]}}   (2 to 4 options)
If the question is already precise, reply exactly: null

SCHEMA:
{schema}

QUESTION: {question}"""


def parse_probe(text: str) -> Optional[Rule]:
    """Turn a model's probe reply into a Rule, or None if it is null or malformed."""
    try:
        data = json.loads(strip_code_fence(text, ("json",)))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        options, seen = [], set()
        for raw in data["options"]:
            label, hint = str(raw.get("label", "")).strip(), str(raw.get("hint", "")).strip()
            if label and hint and label not in seen:
                seen.add(label)
                options.append(Interpretation(id=f"opt{len(options) + 1}", label=label, hint=hint,
                                              default=not options))
            if len(options) == 4:
                break
        term, question = str(data["term"]).strip(), str(data["question"]).strip()
    except (KeyError, TypeError, AttributeError):
        return None
    if len(options) < 2 or not term or not question:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_") or "term"
    return Rule(id=f"probe:{slug}", term=term, question=question, options=tuple(options))


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: Optional[str] = None, client=None):
        self.model = model or os.getenv("ASKFIRST_GEMINI_MODEL", "gemini-2.5-flash")
        self._client = client

    def _get_client(self):
        if self._client is None:
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set (get one at https://aistudio.google.com/apikey).")
            try:
                from google import genai
            except ImportError as exc:
                raise RuntimeError("Install the Gemini extra: pip install 'askfirst[gemini]'") from exc
            self._client = genai.Client(api_key=key)
        return self._client

    def _generate(self, contents: str, system: Optional[str], json_mode: bool = False) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.0,
            response_mime_type="application/json" if json_mode else None)
        return self._get_client().models.generate_content(
            model=self.model, contents=contents, config=config).text

    def generate_sql(self, request: SQLRequest) -> str:
        return extract_sql(self._generate(build_user_prompt(request), SYSTEM))

    def probe(self, question: str, schema: str) -> Optional[Rule]:
        try:
            return parse_probe(self._generate(PROBE_PROMPT.format(schema=schema, question=question), None, True))
        except Exception:  # noqa: BLE001 - a failed probe must never block the question
            return None
