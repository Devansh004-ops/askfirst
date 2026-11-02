"""An offline provider that needs no API key.

It is a small hand-written interpreter for the sample library questions, built
so that AskFirst can be run, demonstrated and tested without a model. It
honours the user's resolved interpretations exactly as a real model would be
told to, which is what lets the evaluation show the effect of asking.

It is NOT a language model: it recognises the sample questions and refuses
everything else. Use `--provider gemini` for real use.
"""
from __future__ import annotations

import re
from typing import Optional

from askfirst.model import Rule, SQLRequest


class OfflineProviderError(RuntimeError):
    pass


def _choice(req: SQLRequest, rule_id: str, fallback: str) -> str:
    for r in req.resolutions:
        if r.rule_id == rule_id:
            return r.interpretation.id
    return fallback


def _window_days(req: SQLRequest, default: int) -> int:
    match = re.fullmatch(r"(\d+)d", _choice(req, "recent_window", f"{default}d"))
    return int(match.group(1)) if match else default


def _book_ranking(req: SQLRequest) -> str:
    how = _choice(req, "book_ranking", "loans")
    if how == "rating":
        return ("SELECT b.title FROM books b JOIN reviews r ON r.book_id = b.book_id "
                "GROUP BY b.book_id HAVING COUNT(*) >= 3 ORDER BY AVG(r.rating) DESC LIMIT 1")
    order = "COUNT(DISTINCT l.member_id)" if how == "borrowers" else "COUNT(*)"
    return ("SELECT b.title FROM books b JOIN loans l ON l.book_id = b.book_id "
            f"GROUP BY b.book_id ORDER BY {order} DESC LIMIT 1")


def _member_ranking(req: SQLRequest) -> str:
    how = _choice(req, "member_ranking", "loans")
    where, order = "", "COUNT(*)"
    if how == "books":
        order = "COUNT(DISTINCT l.book_id)"
    elif how == "recent":
        where = f"WHERE l.loaned_on >= date('{req.today}', '-90 day') "
    elif any(r.rule_id == "recent_window" for r in req.resolutions):
        where = f"WHERE l.loaned_on >= date('{req.today}', '-{_window_days(req, 30)} day') "
    return ("SELECT m.name FROM members m JOIN loans l ON l.member_id = m.member_id "
            f"{where}GROUP BY m.member_id ORDER BY {order} DESC LIMIT 1")


def _active_members(req: SQLRequest) -> str:
    how = _choice(req, "active_members", "loan_30d")
    if how == "open_loan":
        return "SELECT COUNT(DISTINCT member_id) FROM loans WHERE returned_on IS NULL"
    days = 90 if how == "loan_90d" else 30
    return f"SELECT COUNT(DISTINCT member_id) FROM loans WHERE loaned_on >= date('{req.today}', '-{days} day')"


def _grab(pattern: str, text: str) -> str:
    return re.search(pattern, text, re.IGNORECASE).group(1)


# Patterns live in constants because f-string expressions cannot contain backslashes before Python 3.12.
_AFTER_YEAR = r"published after (\d{4})"
_BRANCH = r"the (\w+) branch"
_GENRE = r"the (\w+) genre"
_LOAN_YEAR = r"made in (\d{4})"
_LAST_DAYS = r"last (\d+) days"

_INTENTS: list = [
    (r"top \d+ books by number of loans",
     lambda q, r: "SELECT b.title FROM books b JOIN loans l ON l.book_id = b.book_id "
                  "GROUP BY b.book_id ORDER BY COUNT(*) DESC LIMIT 3"),
    (r"(popular|best).*\bbook|\bbook.*(popular|best)", lambda q, r: _book_ranking(r)),
    (r"\b(top|best|most active)\b.*\bmember", lambda q, r: _member_ranking(r)),
    (r"\bmember.*\bmost active\b", lambda q, r: _member_ranking(r)),
    (r"\brecent loans\b|\bloans\b.*\brecent", lambda q, r: (
        f"SELECT loan_id FROM loans WHERE loaned_on >= date('{r.today}', '-{_window_days(r, 30)} day')")),
    (r"\bactive members?\b", lambda q, r: _active_members(r)),
    (r"currently on loan", lambda q, r: "SELECT COUNT(*) FROM loans WHERE returned_on IS NULL"),
    (_AFTER_YEAR, lambda q, r: f"SELECT title FROM books WHERE published_year > {_grab(_AFTER_YEAR, q)}"),
    (_BRANCH, lambda q, r: f"SELECT COUNT(*) FROM members WHERE branch = '{_grab(_BRANCH, q)}'"),
    (r"\boverdue\b", lambda q, r: f"SELECT loan_id FROM loans WHERE returned_on IS NULL AND due_on < '{r.today}'"),
    (_GENRE, lambda q, r: f"SELECT COUNT(*) FROM books WHERE genre = '{_grab(_GENRE, q)}'"),
    (r"average review rating", lambda q, r: "SELECT AVG(rating) FROM reviews"),
    (_LOAN_YEAR, lambda q, r: f"SELECT COUNT(*) FROM loans WHERE strftime('%Y', loaned_on) = '{_grab(_LOAN_YEAR, q)}'"),
    (r"authors have more than one book",
     lambda q, r: "SELECT author FROM books GROUP BY author HAVING COUNT(*) > 1"),
    (r"never borrowed",
     lambda q, r: "SELECT COUNT(*) FROM members m WHERE NOT EXISTS (SELECT 1 FROM loans l WHERE l.member_id = m.member_id)"),
    (_LAST_DAYS, lambda q, r: (
        f"SELECT COUNT(*) FROM loans WHERE loaned_on >= date('{r.today}', '-{_grab(_LAST_DAYS, q)} day')")),
]


class OfflineDemoProvider:
    name = "offline"

    def generate_sql(self, request: SQLRequest) -> str:
        text = request.question
        for pattern, build in _INTENTS:
            if re.search(pattern, text, re.IGNORECASE):
                return build(text, request)
        raise OfflineProviderError(
            "The offline demo provider only understands the sample questions. "
            "Use --provider gemini for open-ended questions.")

    def probe(self, question: str, schema: str) -> Optional[Rule]:
        return None
