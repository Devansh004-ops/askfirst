"""The pipeline: detect vague terms -> resolve them -> write SQL -> run it safely."""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import date
from typing import Optional

from askfirst.detect import detect
from askfirst.domain import Domain
from askfirst.model import Answer, SQLRequest
from askfirst.resolve import Chooser, PreferenceStore, resolve
from askfirst.sandbox import QueryError, ReadOnlyDB, UnsafeQueryError


class Engine:
    def __init__(self, domain: Domain, db: ReadOnlyDB, provider, *, prefs: Optional[PreferenceStore] = None,
                 glossary: Optional[dict] = None, today: Optional[str] = None, max_repairs: int = 1,
                 probe: bool = False, remember: bool = False):
        self.domain = domain
        self.db = db
        self.provider = provider
        self.prefs = prefs or PreferenceStore()
        self.glossary = domain.glossary if glossary is None else glossary
        self.max_repairs = max_repairs
        self.probe = probe
        self.remember = remember
        # "Today" anchors every relative phrase. Order: explicit > the database's own as-of date > the clock.
        self.today = today or (db.scalar(domain.as_of_query) if domain.as_of_query else None) \
            or date.today().isoformat()
        self._schema: Optional[str] = None

    @property
    def schema(self) -> str:
        if self._schema is None:
            self._schema = self.db.describe()
        return self._schema

    def ask(self, question: str, chooser: Optional[Chooser] = None) -> Answer:
        started = time.perf_counter()
        answer = Answer(question=question)

        rules = detect(question, self.domain.rules)
        if not rules and self.probe:
            try:
                found = self.provider.probe(question, self.schema)
            except Exception:  # noqa: BLE001 - probing is a bonus, never a blocker
                found = None
            rules = [found] if found else []

        answer.resolutions, answer.asked = resolve(
            rules, glossary=self.glossary, prefs=self.prefs, chooser=chooser, remember=self.remember)

        request = SQLRequest(question=question, schema=self.schema, notes=tuple(self.domain.notes),
                             today=self.today, resolutions=tuple(answer.resolutions))
        for attempt in range(self.max_repairs + 1):
            answer.repairs = attempt
            try:
                sql = self.provider.generate_sql(request)
            except Exception as exc:  # noqa: BLE001 - provider/network/config failure: repairing cannot help
                answer.error = f"SQL generation failed: {exc}"
                break
            answer.sql = sql
            try:
                answer.columns, answer.rows, answer.truncated = self.db.query(sql)
                answer.error = None
                break
            except UnsafeQueryError as exc:  # never "repair" a refused query: that would teach probing
                answer.error = f"Blocked by the sandbox: {exc}"
                break
            except QueryError as exc:
                answer.error = str(exc)
                if not exc.repairable:
                    break
                request = replace(request, previous_sql=sql, error=str(exc))

        answer.seconds = time.perf_counter() - started
        return answer
