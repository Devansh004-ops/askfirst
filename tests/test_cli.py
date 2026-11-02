import json
import sqlite3

import pytest

from askfirst.cli import format_table, main


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "cli.db")


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_init_db_creates_a_populated_database_and_refuses_to_overwrite(capsys, db_path):
    code, _, err = run(capsys, "init-db", "--db", db_path)
    assert code == 0 and "Created demo database" in err
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM books").fetchone()[0] == 60
    code, _, err = run(capsys, "init-db", "--db", db_path)
    assert code == 2 and "--force" in err
    assert run(capsys, "init-db", "--db", db_path, "--force")[0] == 0


def test_ask_assume_reports_the_assumption_and_the_result(capsys, db_path):
    code, out, _ = run(capsys, "ask", "--db", db_path, "--assume", "Show me recent loans")
    assert code == 0
    assert "ASSUMED" in out and "The last 30 days" in out and "SELECT loan_id FROM loans" in out
    assert "row(s)" in out


def test_ask_json_is_machine_readable(capsys, db_path):
    code, out, _ = run(capsys, "ask", "--db", db_path, "--assume", "--json", "How many books are currently on loan?")
    data = json.loads(out)
    assert code == 0 and data["error"] is None and data["interpretations"] == []
    assert data["columns"] and data["rows"][0][0] > 0


def test_interactive_choice_is_applied(capsys, monkeypatch, db_path):
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")
    code, out, _ = run(capsys, "ask", "--db", db_path, "--json", "What is the most popular book?")
    data = json.loads(out)
    assert data["interpretations"][0]["meaning"] == "Highest average rating"
    assert data["interpretations"][0]["source"] == "user"


def test_invalid_choice_is_asked_again(capsys, monkeypatch, db_path):
    replies = iter(["9", "0", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    _, out, err = run(capsys, "ask", "--db", db_path, "What is the best book?")
    assert err.count("Please choose 1-3.") == 2 and "Most different borrowers" in out


def test_questions_go_to_stderr_so_stdout_stays_clean(capsys, monkeypatch, db_path):
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    _, out, err = run(capsys, "ask", "--db", db_path, "--json", "Show me recent loans")
    assert "How far back" in err and "How far back" not in out
    json.loads(out)


def test_no_terminal_means_default_with_assumption(capsys, monkeypatch, db_path):
    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    _, out, _ = run(capsys, "ask", "--db", db_path, "How many active members do we have?")
    assert "ASSUMED" in out


def test_remember_then_second_question_is_silent(capsys, monkeypatch, db_path, tmp_path):
    prefs = str(tmp_path / "prefs.json")
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    run(capsys, "ask", "--db", db_path, "--prefs", prefs, "--remember", "What is the best book?")
    assert json.loads(open(prefs).read()) == {"book_ranking": "borrowers"}

    def forbidden(prompt=""):
        raise AssertionError("should not ask again")
    monkeypatch.setattr("builtins.input", forbidden)
    _, out, _ = run(capsys, "ask", "--db", db_path, "--prefs", prefs, "What is the most popular book?")
    assert "your saved choice" in out


def test_unsupported_question_exits_nonzero_with_a_helpful_message(capsys, db_path):
    code, out, _ = run(capsys, "ask", "--db", db_path, "--assume", "Write me a sonnet")
    assert code == 1 and "sample questions" in out


def test_schema_command(capsys, db_path):
    code, out, _ = run(capsys, "schema", "--db", db_path)
    assert code == 0 and "Table loans:" in out and "Today (reference date): 2026-01-15" in out


def test_eval_command_reports_both_modes_and_saves_json(capsys, db_path, tmp_path):
    report = str(tmp_path / "r.json")
    code, out, _ = run(capsys, "eval", "--db", db_path, "--json-out", report)
    assert code == 0 and "=== GUESS ===" in out and "=== ASK ===" in out
    data = json.loads(open(report).read())
    assert [r["mode"] for r in data["runs"]] == ["guess", "ask"]
    assert data["runs"][1]["summary"]["accuracy"] == 100.0


def test_missing_database_for_custom_domain_is_a_clean_error(capsys, tmp_path):
    pack = tmp_path / "pack"; pack.mkdir()
    (pack / "domain.json").write_text("{}")
    with pytest.raises(SystemExit):
        main(["ask", "--domain", str(pack), "--db", str(tmp_path / "nope.db"), "q"])


def test_unknown_domain_is_a_clean_error(capsys, db_path):
    code, _, err = run(capsys, "ask", "--db", db_path, "--domain", "/does/not/exist", "q")
    assert code == 2 and "domain.json" in err


def test_format_table():
    text = format_table(["a", "bb"], [(1, None), (22, "x")])
    assert text.splitlines()[0].startswith("a ") and "NULL" in text and "22" in text
