"""Domain packs: everything AskFirst needs to know about one database.

A pack is a folder containing

    domain.json    name, description, notes for the SQL writer, optional as-of query
    schema.sql     CREATE TABLE statements (used by `init-db` and by tests)
    rules.json     vague phrases worth asking about, and their possible meanings
    glossary.json  (optional) organisation-wide agreed meanings: {rule_id: interpretation_id}
    golden.json    (optional) questions with expected SQL, for `askfirst eval`

Bring your own pack with `--domain path/to/folder`; `library` ships built in.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional

from askfirst.model import Interpretation, Rule

BUILTIN = {"library"}


@dataclass
class Domain:
    name: str
    description: str
    notes: list
    rules: list
    glossary: dict = field(default_factory=dict)
    golden: list = field(default_factory=list)
    as_of_query: Optional[str] = None
    root: Optional[Path] = None

    @property
    def schema_sql(self) -> str:
        return (self.root / "schema.sql").read_text(encoding="utf-8")

    def rule(self, rule_id: str) -> Optional[Rule]:
        return next((r for r in self.rules if r.id == rule_id), None)


def _compile(patterns) -> tuple:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns or ())


def _parse_rule(raw: dict) -> Rule:
    options = tuple(
        Interpretation(id=o["id"], label=o["label"], hint=o["hint"], default=bool(o.get("default", False)))
        for o in raw["options"]
    )
    if len(options) < 2:
        raise ValueError(f"Rule {raw['id']!r} needs at least two options.")
    if sum(o.default for o in options) > 1:
        raise ValueError(f"Rule {raw['id']!r} has more than one default option.")
    if len({o.id for o in options}) != len(options):
        raise ValueError(f"Rule {raw['id']!r} has duplicate option ids.")
    return Rule(id=raw["id"], term=raw["term"], question=raw["question"], options=options,
                when_all=_compile(raw.get("when_all")), unless=_compile(raw.get("unless")))


def load_domain(spec: str | Path = "library", glossary_path: Optional[str | Path] = None) -> Domain:
    """Load a built-in pack by name or a pack folder by path."""
    if isinstance(spec, str) and spec in BUILTIN:
        root = Path(str(resources.files("askfirst") / "domains" / spec))
    else:
        root = Path(spec)
    if not (root / "domain.json").exists():
        raise FileNotFoundError(f"Not a domain pack (no domain.json): {root}")

    def read(name, default):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    meta = read("domain.json", {})
    rules = [_parse_rule(r) for r in read("rules.json", [])]
    glossary = read("glossary.json", {})
    if glossary_path:
        glossary = {**glossary, **json.loads(Path(glossary_path).read_text(encoding="utf-8"))}

    known = {r.id: r for r in rules}
    for rule_id, option_id in glossary.items():
        if rule_id not in known or known[rule_id].option(option_id) is None:
            raise ValueError(f"Glossary entry {rule_id!r}: {option_id!r} is not a defined rule/option.")

    return Domain(name=meta.get("name", root.name), description=meta.get("description", ""),
                  notes=list(meta.get("notes", [])), rules=rules, glossary=glossary,
                  golden=read("golden.json", []), as_of_query=meta.get("as_of_query"), root=root)
