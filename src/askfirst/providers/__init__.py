"""SQL providers: anything that can turn a `SQLRequest` into a query string."""
from __future__ import annotations

from typing import Optional, Protocol

from askfirst.model import Rule, SQLRequest


class Provider(Protocol):
    name: str

    def generate_sql(self, request: SQLRequest) -> str:
        """Return one SELECT statement (or raise)."""

    def probe(self, question: str, schema: str) -> Optional[Rule]:
        """Optionally spot a vague term the domain rules do not cover. Return None if none."""


def make_provider(name: str):
    if name == "offline":
        from askfirst.providers.offline import OfflineDemoProvider
        return OfflineDemoProvider()
    if name == "gemini":
        from askfirst.providers.gemini import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"Unknown provider {name!r}. Choose 'offline' or 'gemini'.")
