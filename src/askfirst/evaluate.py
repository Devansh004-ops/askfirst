"""Golden-set evaluation: does asking first actually produce the right answers?

Each golden case has an `expected_sql`. A case is correct only if the result of
the query the engine produced is *equivalent* to the expected result (see
scoring.py): "it ran" is not "it is right".

Two modes, run through the real Engine:
  ask    the engine asks; a scripted user answers with the case's intended meaning
  guess  the engine never asks; defaults are assumed (what a system without a
         clarification step would do)
"""
from __future__ import annotations

from typing import Optional

from askfirst.engine import Engine
from askfirst.scoring import equivalent

EXPORT_ROWS = 10_000


def _pct(n: int, d: int) -> Optional[float]:
    return round(100 * n / d, 1) if d else None


def run_case(engine: Engine, case: dict, mode: str) -> dict:
    scripted = case.get("answers", {})
    chooser = (lambda rule: scripted.get(rule.id)) if mode == "ask" else None
    answer = engine.ask(case["question"], chooser)

    expected_sql = case["expected_sql"].replace("{today}", engine.today)
    _, expected_rows, _ = engine.db.query(expected_sql, max_rows=EXPORT_ROWS)

    correct = False
    if answer.ok:
        try:
            _, actual_rows, _ = engine.db.query(answer.sql, max_rows=EXPORT_ROWS)
            correct = equivalent(expected_rows, actual_rows, ordered=bool(case.get("ordered")))
        except Exception as exc:  # noqa: BLE001
            answer.error = str(exc)
    return {
        "id": case["id"], "question": case["question"], "kind": case["kind"],
        "detected": bool(answer.resolutions),   # a vague term was found, however it was then resolved
        "correct": correct, "error": answer.error, "sql": answer.sql,
        "repairs": answer.repairs, "seconds": round(answer.seconds, 3),
        "expected_rows": len(expected_rows),
    }


def summarize(rows: list) -> dict:
    ambiguous = [r for r in rows if r["kind"] == "ambiguous"]
    clear = [r for r in rows if r["kind"] == "clear"]
    return {
        "cases": len(rows),
        "accuracy": _pct(sum(r["correct"] for r in rows), len(rows)),
        "accuracy_on_ambiguous": _pct(sum(r["correct"] for r in ambiguous), len(ambiguous)),
        "accuracy_on_clear": _pct(sum(r["correct"] for r in clear), len(clear)),
        "detection_recall": _pct(sum(r["detected"] for r in ambiguous), len(ambiguous)),
        "false_alarm_rate": _pct(sum(r["detected"] for r in clear), len(clear)),
        "errors": sum(1 for r in rows if r["error"]),
        "queries_repaired": sum(1 for r in rows if r["repairs"] and not r["error"]),
        "empty_expected_results": sum(1 for r in rows if r["expected_rows"] == 0),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / max(len(rows), 1), 3),
    }


def run_eval(engine: Engine, mode: str) -> dict:
    rows = [run_case(engine, case, mode) for case in engine.domain.golden]
    return {"mode": mode, "summary": summarize(rows), "cases": rows}
