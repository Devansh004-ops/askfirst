"""A read-only SQLite sandbox for model-written SQL.

Instead of scanning the SQL text for forbidden words (which parsers and
attackers disagree about), the sandbox lets SQLite itself say what a statement
*does*. SQLite calls an "authorizer" for every action it is about to perform
while compiling a statement: reading a column, calling a function, writing,
attaching a file, running a PRAGMA... The sandbox approves only:

  * SELECT itself (and recursive CTEs),
  * reading columns of tables on an allowlist,
  * calling functions on an allowlist (no load_extension, no random()).

Everything else -- INSERT/UPDATE/DELETE, DDL, PRAGMA, ATTACH, transactions,
reading `sqlite_master` -- is refused by the engine, whatever the SQL looks like.

Further layers: the file is opened `mode=ro`, `PRAGMA query_only` is on, a
progress handler enforces a wall-clock timeout, rows are capped, and SQLite
already refuses a second statement in one call.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional

_SQLITE_SELECT = getattr(sqlite3, "SQLITE_SELECT", 21)
_SQLITE_READ = getattr(sqlite3, "SQLITE_READ", 20)
_SQLITE_FUNCTION = getattr(sqlite3, "SQLITE_FUNCTION", 31)
_SQLITE_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)

DEFAULT_FUNCTIONS = frozenset({
    # aggregates
    "count", "sum", "avg", "min", "max", "total", "group_concat",
    # scalar
    "abs", "round", "coalesce", "ifnull", "nullif", "iif", "length", "lower", "upper",
    "substr", "substring", "trim", "ltrim", "rtrim", "replace", "instr", "printf", "format",
    "typeof", "like", "glob", "likely", "unlikely", "hex",
    # dates
    "date", "time", "datetime", "julianday", "strftime", "unixepoch",
    # window
    "row_number", "rank", "dense_rank", "ntile", "lag", "lead", "first_value", "last_value",
    "cume_dist", "percent_rank",
})


class QueryError(Exception):
    """The query failed. `repairable` says whether asking the model to fix it could help."""

    def __init__(self, message: str, repairable: bool = False):
        super().__init__(message)
        self.repairable = repairable


class UnsafeQueryError(QueryError):
    """The sandbox refused the query. Never repairable: retrying would only probe the limits."""

    def __init__(self, message: str):
        super().__init__(message, repairable=False)


class QueryTimeout(QueryError):
    def __init__(self, seconds: float):
        super().__init__(f"Query exceeded the {seconds:g}s time limit.", repairable=False)


class ReadOnlyDB:
    """Opens a SQLite file for model-written queries, safely."""

    def __init__(self, path: str | Path, *, tables: Optional[Iterable[str]] = None,
                 functions: Iterable[str] = DEFAULT_FUNCTIONS, timeout_s: float = 5.0, max_rows: int = 200):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Database not found: {self.path}")
        self.timeout_s = timeout_s
        self.max_rows = max_rows
        self._functions = frozenset(f.lower() for f in functions)
        # Introspection connection: also read-only, but never exposed to model SQL.
        self._admin = self._connect()
        self.tables = tuple(sorted(
            t.lower() for t in (tables if tables is not None else self._user_tables())
        ))

    # ------------------------------------------------------------------ setup
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        return conn

    def _user_tables(self) -> list:
        rows = self._admin.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' AND name NOT LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._admin.close()

    # -------------------------------------------------------------- authorizer
    def _make_authorizer(self, denied: list):
        """Authorizer for one statement; appends a description of anything it refuses to `denied`."""

        def authorize(action, param1, param2, db_name, _source):
            if action in (_SQLITE_SELECT, _SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            if action == _SQLITE_READ:
                # db_name is None for things SQLite builds on the fly (a CTE reading itself,
                # sub-select results); every stored table or virtual table reports "main"/"temp".
                if db_name is None or (param1 or "").lower() in self.tables:
                    return sqlite3.SQLITE_OK
                denied.append(f"reading {param1}")
            elif action == _SQLITE_FUNCTION:
                if (param2 or "").lower() in self._functions:
                    return sqlite3.SQLITE_OK
                denied.append(f"calling {param2}()")
            else:
                denied.append("a statement other than SELECT")
            return sqlite3.SQLITE_DENY

        return authorize

    # ------------------------------------------------------------------- query
    def query(self, sql: str, max_rows: Optional[int] = None):
        """Run one SELECT. Returns (columns, rows, truncated)."""
        sql = (sql or "").strip().rstrip(";").strip()
        if not sql:
            raise UnsafeQueryError("Empty query.")
        limit = self.max_rows if max_rows is None else max_rows

        conn = self._connect()
        deadline = time.monotonic() + self.timeout_s
        timed_out, denied = [], []

        def _progress():
            if time.monotonic() > deadline:
                timed_out.append(True)
                return 1  # non-zero aborts the running statement
            return 0

        try:
            conn.set_authorizer(self._make_authorizer(denied))
            conn.set_progress_handler(_progress, 10_000)
            cursor = conn.execute(sql)
            columns = [d[0] for d in (cursor.description or [])]
            rows = cursor.fetchmany(limit + 1)
        except sqlite3.ProgrammingError as exc:  # e.g. "only one statement at a time"
            raise UnsafeQueryError(str(exc)) from None
        except sqlite3.DatabaseError as exc:
            if timed_out:
                raise QueryTimeout(self.timeout_s) from None
            if denied:  # SQLite words refusals several ways, so rely on what we recorded, not on the text
                raise UnsafeQueryError(
                    f"Not allowed: {denied[0]}. Queries may only read these tables with ordinary "
                    f"functions: {', '.join(self.tables)}."
                ) from None
            message = str(exc)
            # Syntax errors, unknown columns, ... : the model can plausibly fix these.
            raise QueryError(message, repairable=True) from None
        finally:
            conn.close()

        return columns, [tuple(r) for r in rows[:limit]], len(rows) > limit

    # ------------------------------------------------------------ introspection
    def scalar(self, sql: str):
        """Trusted internal lookup (never fed model SQL). Returns None on any failure."""
        try:
            row = self._admin.execute(sql).fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def describe(self, *, sample_limit: int = 8) -> str:
        """Schema text for the model: columns, keys, and values of small text columns."""
        lines = []
        for table in self.tables:
            cols = self._admin.execute(f'PRAGMA table_info("{table}")').fetchall()
            fks = {r[3]: f"{r[2]}.{r[4]}" for r in self._admin.execute(f'PRAGMA foreign_key_list("{table}")')}
            lines.append(f"Table {table}:")
            for _cid, name, ctype, notnull, _default, pk in cols:
                notes = []
                if pk:
                    notes.append("primary key")
                if name in fks:
                    notes.append(f"references {fks[name]}")
                if not notnull and not pk:
                    notes.append("nullable")
                if (ctype or "").upper() == "TEXT" and not pk and name not in fks:
                    values = [r[0] for r in self._admin.execute(
                        f'SELECT DISTINCT "{name}" FROM "{table}" WHERE "{name}" IS NOT NULL '
                        f"LIMIT {sample_limit + 1}")]
                    if 0 < len(values) <= sample_limit and not _looks_like_date(values):
                        notes.append("values: " + ", ".join(repr(v) for v in sorted(values)))
                annotation = ("  [" + "; ".join(notes) + "]") if notes else ""
                lines.append(f"  {name} {ctype.lower() or 'any'}{annotation}")
        return "\n".join(lines)


def _looks_like_date(values) -> bool:
    return all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", v) for v in values)
