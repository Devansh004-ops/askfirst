"""Command-line interface: init-db, ask, repl, schema, eval."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from askfirst.domain import BUILTIN, load_domain
from askfirst.engine import Engine
from askfirst.evaluate import run_eval
from askfirst.model import SOURCE_ASSUMED, SOURCE_GLOSSARY, SOURCE_PREFERENCE, SOURCE_USER, Answer
from askfirst.providers import make_provider
from askfirst.resolve import PreferenceStore
from askfirst.sandbox import ReadOnlyDB

DEFAULT_DB = "askfirst.db"
DEFAULT_TODAY = "2026-01-15"

_SOURCE_TEXT = {
    SOURCE_USER: "you chose",
    SOURCE_PREFERENCE: "your saved choice",
    SOURCE_GLOSSARY: "organisation glossary",
    SOURCE_ASSUMED: "ASSUMED - nobody answered",
}


# ------------------------------------------------------------------ helpers
def format_table(columns, rows) -> str:
    if not columns:
        return "(no columns)"
    cells = [[("NULL" if v is None else str(v)) for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    line = lambda parts: "  ".join(p.ljust(w) for p, w in zip(parts, widths)).rstrip()  # noqa: E731
    return "\n".join([line(columns), line(["-" * w for w in widths])] + [line(r) for r in cells])


def prompt_chooser(rule):
    """Ask on stderr so that stdout stays clean for --json and for piping."""
    err = sys.stderr
    print(f"\n{rule.question}   [about: {rule.term}]", file=err)
    for i, option in enumerate(rule.options, 1):
        print(f"  [{i}] {option.label}{'   (default)' if option.default else ''}", file=err)
    while True:
        print("Pick a number, type your own meaning, or press Enter for the default: ", end="", file=err, flush=True)
        try:
            reply = input().strip()
        except EOFError:
            print(file=err)
            return None
        if reply.isdigit() and not 1 <= int(reply) <= len(rule.options):
            print(f"  Please choose 1-{len(rule.options)}.", file=err)
            continue
        return reply or None


def answer_to_dict(answer: Answer) -> dict:
    return {
        "question": answer.question,
        "interpretations": [{"rule": r.rule_id, "term": r.term, "meaning": r.interpretation.label,
                             "source": r.source} for r in answer.resolutions],
        "sql": answer.sql, "columns": answer.columns, "rows": answer.rows, "truncated": answer.truncated,
        "error": answer.error, "repairs": answer.repairs, "seconds": round(answer.seconds, 3),
    }


def print_answer(answer: Answer) -> None:
    for r in answer.resolutions:
        print(f'\n"{r.term}" -> {r.interpretation.label}   ({_SOURCE_TEXT[r.source]})')
    if answer.assumptions:
        print("Tip: run without --assume to be asked instead of assuming.")
    if answer.sql:
        print(f"\nSQL:\n{answer.sql}")
    if answer.error:
        print(f"\nError: {answer.error}")
        return
    if not answer.rows:
        print("\nNo rows.")
        return
    print(f"\n{format_table(answer.columns, answer.rows)}")
    note = f"{len(answer.rows)} row(s)"
    if answer.truncated:
        note += " (truncated at the row limit)"
    if answer.repairs:
        note += f", query repaired {answer.repairs}x"
    print(f"\n[{note}, {answer.seconds:.2f}s]")


def ensure_database(path: Path, domain_name: str, today: str, quiet: bool = False) -> None:
    if path.exists():
        return
    if domain_name not in BUILTIN:
        raise SystemExit(f"error: database {path} does not exist (create it, then pass --db).")
    seed = importlib.import_module(f"askfirst.domains.{domain_name}.seed")
    counts = seed.generate(path, today=today)
    if not quiet:
        print(f"Created demo database {path} ({', '.join(f'{v} {k}' for k, v in counts.items())}).",
              file=sys.stderr)


def build_engine(args) -> Engine:
    domain = load_domain(args.domain, glossary_path=getattr(args, "glossary", None))
    db_path = Path(args.db)
    ensure_database(db_path, args.domain, getattr(args, "today", None) or DEFAULT_TODAY)
    provider = make_provider(args.provider)
    if args.provider == "offline":
        print("Using the offline demo provider (sample questions only; try --provider gemini).",
              file=sys.stderr)
    prefs = PreferenceStore(getattr(args, "prefs", None))
    return Engine(domain, ReadOnlyDB(db_path), provider, prefs=prefs, today=getattr(args, "today", None),
                  probe=getattr(args, "probe", False), remember=getattr(args, "remember", False))


# ---------------------------------------------------------------- commands
def cmd_init_db(args) -> int:
    path = Path(args.db)
    if path.exists() and not args.force:
        print(f"error: {path} exists (use --force to replace it).", file=sys.stderr)
        return 2
    if args.domain in BUILTIN:
        path.unlink(missing_ok=True)
        ensure_database(path, args.domain, args.today, quiet=False)
        return 0
    domain = load_domain(args.domain)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(domain.schema_sql)
    conn.close()
    print(f"Created empty database {path} from {args.domain}/schema.sql.")
    return 0


def _ask_once(engine: Engine, question: str, args) -> Answer:
    answer = engine.ask(question, None if args.assume else prompt_chooser)
    if args.json:
        print(json.dumps(answer_to_dict(answer), indent=2, default=str))
    else:
        print_answer(answer)
    return answer


def cmd_ask(args) -> int:
    engine = build_engine(args)
    return 0 if _ask_once(engine, " ".join(args.question), args).ok else 1


def cmd_repl(args) -> int:
    engine = build_engine(args)
    print("Type a question and press Enter. A blank line exits.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        _ask_once(engine, question, args)


def cmd_schema(args) -> int:
    engine = build_engine(args)
    print(engine.schema)
    if engine.domain.notes:
        print("\nNotes:\n" + "\n".join(f"- {n}" for n in engine.domain.notes))
    print(f"\nToday (reference date): {engine.today}")
    return 0


def cmd_eval(args) -> int:
    engine = build_engine(args)
    if not engine.domain.golden:
        print("error: this domain has no golden.json.", file=sys.stderr)
        return 2
    modes = ["guess", "ask"] if args.mode == "both" else [args.mode]
    report = {"provider": args.provider, "reference_date": engine.today, "runs": []}
    for mode in modes:
        run = run_eval(engine, mode)
        report["runs"].append(run)
        print(f"\n=== {mode.upper()} ===")
        for row in run["cases"]:
            print(f"  [{'OK ' if row['correct'] else 'BAD'}] {row['id']}  {row['question']}"
                  + (f"   <- {row['error']}" if row["error"] else ""))
        print(json.dumps(run["summary"], indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved {args.json_out}")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=os.getenv("ASKFIRST_DB", DEFAULT_DB), help="SQLite file (default %(default)s)")
    common.add_argument("--domain", default="library", help="built-in pack name or path to a pack folder")
    common.add_argument("--provider", default=os.getenv("ASKFIRST_PROVIDER", "offline"),
                        choices=["offline", "gemini"], help="SQL writer (default %(default)s)")
    common.add_argument("--today", help="reference date for relative phrases (default: the database's own)")
    common.add_argument("--glossary", help="JSON file {rule_id: option_id} of agreed meanings")

    interactive = argparse.ArgumentParser(add_help=False)
    interactive.add_argument("--assume", action="store_true",
                             help="never ask; use defaults and report them as assumptions")
    interactive.add_argument("--prefs", help="JSON file where your choices are remembered")
    interactive.add_argument("--remember", action="store_true", help="save each choice to --prefs")
    interactive.add_argument("--probe", action="store_true",
                             help="let the model flag vague terms the rules miss (gemini only)")
    interactive.add_argument("--json", action="store_true", help="print machine-readable output")

    parser = argparse.ArgumentParser(prog="askfirst", description="Ask your database questions; it asks back when unsure.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="create the demo database")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--domain", default="library")
    p.add_argument("--today", default=DEFAULT_TODAY, help="reference date stored in the database")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("ask", parents=[common, interactive], help="answer one question")
    p.add_argument("question", nargs="+")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("repl", parents=[common, interactive], help="interactive session")
    p.set_defaults(func=cmd_repl)

    p = sub.add_parser("schema", parents=[common], help="show what the model is told about the database")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("eval", parents=[common], help="run the domain's golden questions")
    p.add_argument("--mode", choices=["ask", "guess", "both"], default="both")
    p.add_argument("--json-out", help="write the full report here")
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
