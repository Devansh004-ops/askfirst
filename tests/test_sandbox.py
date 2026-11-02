import hashlib

import pytest

from askfirst import QueryError, ReadOnlyDB, UnsafeQueryError
from askfirst.sandbox import QueryTimeout


def test_reads_allowed_tables_and_functions(db):
    cols, rows, truncated = db.query("SELECT COUNT(*), MAX(published_year) FROM books")
    assert cols == ["COUNT(*)", "MAX(published_year)"] and rows[0][0] == 60 and not truncated


def test_joins_ctes_windows_and_dates_work(db):
    sql = """WITH t AS (SELECT member_id, COUNT(*) n FROM loans GROUP BY 1)
             SELECT member_id, n, RANK() OVER (ORDER BY n DESC), date('2026-01-15', '-30 day') FROM t LIMIT 3"""
    assert len(db.query(sql)[1]) == 3


def test_trailing_semicolon_and_whitespace_are_fine(db):
    assert db.query("  SELECT 1;  ")[1] == [(1,)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM loans",
    "UPDATE members SET name = 'x'",
    "INSERT INTO books VALUES (999,'a','b','c',2000)",
    "DROP TABLE loans",
    "CREATE TABLE evil (x)",
    "ALTER TABLE books ADD COLUMN x",
    "ATTACH DATABASE '/tmp/other.db' AS other",
    "PRAGMA writable_schema = ON",
    "PRAGMA table_info(books)",
    "VACUUM",
    "REINDEX",
    "BEGIN",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM sqlite_schema",
    "SELECT * FROM _askfirst_meta",                                   # internal table is hidden
    "SELECT * FROM books WHERE book_id IN (SELECT value FROM _askfirst_meta)",   # ...even inside a subquery
    "SELECT load_extension('/tmp/x.so')",
    "SELECT random()",
    "SELECT * FROM pragma_table_info('books')",                       # table-valued PRAGMA functions
    "WITH x AS (SELECT 1) DELETE FROM loans",
    "SELECT 1; DELETE FROM loans",                                    # second statement
    "SELECT 1; SELECT 2",
])
def test_everything_but_plain_reads_is_refused(db, sql):
    with pytest.raises(UnsafeQueryError):
        db.query(sql)


def test_functions_that_do_not_exist_cannot_be_used_either(db):
    with pytest.raises(QueryError):
        db.query("SELECT readfile('/etc/passwd')")


def test_refusal_names_what_was_denied(db):
    with pytest.raises(UnsafeQueryError, match="sqlite_master"):
        db.query("SELECT * FROM sqlite_master")
    with pytest.raises(UnsafeQueryError, match=r"random\(\)"):
        db.query("SELECT random()")


def test_recursive_cte_may_read_itself(db):
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT SUM(n) FROM r"
    assert db.query(sql)[1] == [(15,)]


def test_empty_query_is_refused(db):
    with pytest.raises(UnsafeQueryError):
        db.query("   ;  ")


def test_database_file_is_never_modified(demo_db, db):
    before = hashlib.sha256(demo_db.read_bytes()).hexdigest()
    for sql in ("DELETE FROM loans", "DROP TABLE books", "UPDATE members SET name='x'", "SELECT 1; DROP TABLE loans"):
        with pytest.raises(QueryError):
            db.query(sql)
    assert hashlib.sha256(demo_db.read_bytes()).hexdigest() == before


def test_file_is_opened_read_only_even_without_the_authorizer(demo_db):
    """Layer below the authorizer: a raw connection to the same URI cannot write either."""
    import sqlite3
    conn = sqlite3.connect(demo_db.resolve().as_uri() + "?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM loans")


def test_unknown_column_is_a_repairable_error_not_a_security_error(db):
    with pytest.raises(QueryError) as info:
        db.query("SELECT nonexistent FROM books")
    assert info.value.repairable and not isinstance(info.value, UnsafeQueryError)
    assert "nonexistent" in str(info.value)


def test_syntax_error_is_repairable(db):
    with pytest.raises(QueryError) as info:
        db.query("SELEC 1")
    assert info.value.repairable


def test_unsafe_errors_are_never_repairable(db):
    with pytest.raises(UnsafeQueryError) as info:
        db.query("DROP TABLE loans")
    assert info.value.repairable is False


def test_row_cap_and_truncation_flag(db):
    cols, rows, truncated = db.query("SELECT * FROM loans", max_rows=5)
    assert len(rows) == 5 and truncated
    _, rows, truncated = db.query("SELECT * FROM books", max_rows=60)
    assert len(rows) == 60 and not truncated


def test_runaway_query_is_stopped(demo_db):
    slow = ReadOnlyDB(demo_db, timeout_s=0.3)
    with pytest.raises(QueryTimeout):
        slow.query("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r")
    slow.close()


def test_missing_database_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReadOnlyDB(tmp_path / "nope.db")


def test_describe_lists_tables_keys_and_small_value_sets(db):
    text = db.describe()
    assert "Table loans:" in text and "references books.book_id" in text and "primary key" in text
    assert "'Mystery'" in text and "'Riverside'" in text          # small text columns list their values
    assert "returned_on text  [nullable]" in text
    assert "_askfirst_meta" not in text                            # internal table is not advertised
    assert "title text" in text and "values:" not in text.split("title text")[1].split("\n")[0]   # high-cardinality: no values
