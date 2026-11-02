"""Decide what each vague term means, asking the user only as a last resort.

Order of precedence for every fired rule:

  1. the user's saved preference            (they told us before)
  2. the organisation glossary              (an agreed definition)
  3. ask the user                           (via the `chooser` callback)
  4. the rule's default, reported as an assumption

Saved preferences come first so one person's habit overrides the house default
for them only; the glossary exists so that the *same* term never has to be asked
about at all inside an organisation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional, Sequence, Union

from askfirst.model import (SOURCE_ASSUMED, SOURCE_GLOSSARY, SOURCE_PREFERENCE, SOURCE_USER,
                            Interpretation, Resolution, Rule)

# A chooser receives the rule and returns: an option id, a 1-based option number,
# free text (used as a custom meaning), or None to decline.
Chooser = Callable[[Rule], Union[str, int, None]]


class PreferenceStore:
    """Remembers {rule_id: interpretation_id}, optionally in a JSON file."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self._data: dict = {}
        if self.path and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}  # a corrupt file must never block a question

    def get(self, rule_id: str) -> Optional[str]:
        return self._data.get(rule_id)

    def set(self, rule_id: str, option_id: str) -> None:
        self._data[rule_id] = option_id
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

    def forget(self, rule_id: Optional[str] = None) -> None:
        self._data = {} if rule_id is None else {k: v for k, v in self._data.items() if k != rule_id}
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")


def interpret_reply(rule: Rule, reply: Union[str, int, None]) -> Optional[Interpretation]:
    """Turn a chooser reply into an Interpretation, or None if it declines or is invalid."""
    if reply is None:
        return None
    if isinstance(reply, int) or (isinstance(reply, str) and reply.strip().isdigit()):
        index = int(reply)
        return rule.options[index - 1] if 1 <= index <= len(rule.options) else None
    text = str(reply).strip()
    if not text:
        return None
    known = rule.option(text)
    if known:
        return known
    return Interpretation(id="custom", label=text, hint=f'The user defines "{rule.term}" as: {text}')


def resolve(rules: Sequence[Rule], *, glossary: dict, prefs: PreferenceStore,
            chooser: Optional[Chooser], remember: bool = False):
    """Returns (resolutions, asked_rule_ids)."""
    resolutions, asked = [], []
    for rule in rules:
        saved = rule.option(prefs.get(rule.id) or "")
        if saved:
            resolutions.append(Resolution(rule.id, rule.term, saved, SOURCE_PREFERENCE))
            continue
        agreed = rule.option(glossary.get(rule.id, ""))
        if agreed:
            resolutions.append(Resolution(rule.id, rule.term, agreed, SOURCE_GLOSSARY))
            continue
        chosen = None
        if chooser is not None:
            asked.append(rule.id)
            chosen = interpret_reply(rule, chooser(rule))
        if chosen:
            resolutions.append(Resolution(rule.id, rule.term, chosen, SOURCE_USER))
            if remember and chosen.id != "custom":
                prefs.set(rule.id, chosen.id)
        else:
            resolutions.append(Resolution(rule.id, rule.term, rule.default_option, SOURCE_ASSUMED))
    return resolutions, asked
