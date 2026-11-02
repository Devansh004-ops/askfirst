"""Plain data types shared by every part of AskFirst."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

# Where the interpretation used for a vague term came from.
SOURCE_GLOSSARY = "glossary"        # the organisation's agreed definition
SOURCE_PREFERENCE = "preference"    # the user's remembered earlier choice
SOURCE_USER = "user"                # the user answered just now
SOURCE_ASSUMED = "assumed"          # nobody answered; the default was used (and is reported)


@dataclass(frozen=True)
class Interpretation:
    """One concrete meaning of a vague term."""

    id: str
    label: str            # shown to the user
    hint: str             # instruction handed to the SQL generator
    default: bool = False  # used (and flagged as an assumption) when nobody answers


@dataclass(frozen=True)
class Rule:
    """A vague phrase worth asking about, plus the meanings it can have.

    A rule fires when every `when_all` pattern matches the question and no
    `unless` pattern does (`unless` holds the words that already pin the meaning
    down, e.g. "by number of loans").
    """

    id: str
    term: str
    question: str
    options: Sequence[Interpretation]
    when_all: Sequence[re.Pattern] = field(default_factory=tuple)
    unless: Sequence[re.Pattern] = field(default_factory=tuple)

    def matches(self, question: str) -> bool:
        if not self.when_all:  # rules without patterns (e.g. proposed by a model) never match by text
            return False
        return all(p.search(question) for p in self.when_all) and not any(p.search(question) for p in self.unless)

    def option(self, key: str) -> Optional[Interpretation]:
        return next((o for o in self.options if o.id == key), None)

    @property
    def default_option(self) -> Interpretation:
        return next((o for o in self.options if o.default), self.options[0])


@dataclass(frozen=True)
class Resolution:
    rule_id: str
    term: str
    interpretation: Interpretation
    source: str


@dataclass(frozen=True)
class SQLRequest:
    """Everything a provider needs to write (or repair) one query."""

    question: str
    schema: str
    notes: Sequence[str]
    today: str                              # ISO date; relative phrases are measured from here
    resolutions: Sequence[Resolution] = ()
    previous_sql: Optional[str] = None      # set when repairing
    error: Optional[str] = None


@dataclass
class Answer:
    question: str
    resolutions: list = field(default_factory=list)
    asked: list = field(default_factory=list)      # rule ids the user was actually asked about
    sql: Optional[str] = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None
    repairs: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def assumptions(self) -> list:
        return [r for r in self.resolutions if r.source == SOURCE_ASSUMED]
