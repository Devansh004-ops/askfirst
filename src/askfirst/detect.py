"""Find vague phrases in a question: deterministic, free, and explainable."""
from __future__ import annotations

from typing import Sequence

from askfirst.model import Rule


def detect(question: str, rules: Sequence[Rule]) -> list:
    """Rules that fire for this question, in rule order, each at most once."""
    seen, fired = set(), []
    for rule in rules:
        if rule.id not in seen and rule.matches(question):
            seen.add(rule.id)
            fired.append(rule)
    return fired
