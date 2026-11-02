"""The built-in domain: seed determinism, planted facts, golden set sanity, benchmark behaviour."""
import sqlite3

import pytest

from askfirst import Engine, ReadOnlyDB
from askfirst.domains.library.seed import generate
from askfirst.evaluate import run_eval
from askfirst.providers.offline import OfflineDemoProvider, OfflineProviderError
from askfirst.model import SQLRequest

TODAY = "2026-01-15"


def rows(db, sql):
    return db.query(sql)[1]


def test_seed_is_deterministic(tmp_path):
    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    generate(a, seed=7, today=TODAY)
    generate(b, seed=7, today=TODAY)
    generate(c, seed=8, today=TODAY)
    dump = lambda p: list(sqlite3.connect(p).iterdump())  # noqa: E731
    assert dump(a) == dump(b)
    assert dump(a) != dump(c)


def test_seed_replaces_an_existing_file(tmp_path):
    path = tmp_path / "x.db"
    generate(path); generate(path)
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM members").fetchone()[0] == 40


def test_no_dates_are_in_the_future_and_loans_are_consistent(db):
    assert rows(db, f"SELECT COUNT(*) FROM loans WHERE loaned_on > '{TODAY}' OR returned_on > '{TODAY}'") == [(0,)]
    assert rows(db, "SELECT COUNT(*) FROM loans WHERE returned_on < loaned_on") == [(0,)]
    assert rows(db, "SELECT COUNT(*) FROM reviews r WHERE r.rating NOT BETWEEN 1 AND 5") == [(0,)]


def test_planted_facts_give_every_reading_a_different_unique_winner(db):
    top = lambda sql: rows(db, sql + " LIMIT 2")  # noqa: E731
    by_loans = top("SELECT book_id, COUNT(*) n FROM loans GROUP BY 1 ORDER BY n DESC")
    by_borrowers = top("SELECT book_id, COUNT(DISTINCT member_id) n FROM loans GROUP BY 1 ORDER BY n DESC")
    by_rating = top("SELECT book_id, AVG(rating) a FROM reviews GROUP BY 1 HAVING COUNT(*) >= 3 ORDER BY a DESC")
    winners = {by_loans[0][0], by_borrowers[0][0], by_rating[0][0]}
    assert winners == {3, 12, 25}
    for ranking in (by_loans, by_borrowers, by_rating):
        assert ranking[0][1] > ranking[1][1], "winner must be unique"

    m_loans = top("SELECT member_id, COUNT(*) n FROM loans GROUP BY 1 ORDER BY n DESC")
    m_books = top("SELECT member_id, COUNT(DISTINCT book_id) n FROM loans GROUP BY 1 ORDER BY n DESC")
    m_90 = top(f"SELECT member_id, COUNT(*) n FROM loans WHERE loaned_on >= date('{TODAY}','-90 day') GROUP BY 1 ORDER BY n DESC")
    m_30 = top(f"SELECT member_id, COUNT(*) n FROM loans WHERE loaned_on >= date('{TODAY}','-30 day') GROUP BY 1 ORDER BY n DESC")
    assert (m_loans[0][0], m_books[0][0], m_90[0][0], m_30[0][0]) == (5, 8, 27, 11)
    for ranking in (m_loans, m_books, m_90, m_30):
        assert ranking[0][1] > ranking[1][1]


def test_three_members_never_borrowed(db):
    assert rows(db, "SELECT COUNT(*) FROM members m WHERE NOT EXISTS (SELECT 1 FROM loans l WHERE l.member_id=m.member_id)") == [(3,)]


def test_the_three_meanings_of_active_give_different_counts(db):
    a = rows(db, f"SELECT COUNT(DISTINCT member_id) FROM loans WHERE loaned_on >= date('{TODAY}','-30 day')")
    b = rows(db, "SELECT COUNT(DISTINCT member_id) FROM loans WHERE returned_on IS NULL")
    c = rows(db, f"SELECT COUNT(DISTINCT member_id) FROM loans WHERE loaned_on >= date('{TODAY}','-90 day')")
    assert len({a[0][0], b[0][0], c[0][0]}) == 3


def test_golden_questions_are_well_formed_and_nonempty(domain, db):
    ids = [c["id"] for c in domain.golden]
    assert len(ids) == len(set(ids)) and len(ids) >= 15
    kinds = {c["kind"] for c in domain.golden}
    assert kinds == {"clear", "ambiguous"}
    for case in domain.golden:
        assert (case["kind"] == "ambiguous") == ("answers" in case), case["id"]
        result = rows(db, case["expected_sql"].replace("{today}", TODAY))
        assert result, f"{case['id']} expects an empty result, which would make a match meaningless"
        for rule_id, option_id in case.get("answers", {}).items():
            assert domain.rule(rule_id).option(option_id), (case["id"], rule_id, option_id)


def test_golden_ambiguous_cases_are_detected_and_clear_ones_are_not(domain):
    from askfirst.detect import detect
    for case in domain.golden:
        fired = {r.id for r in detect(case["question"], domain.rules)}
        expected = set(case.get("answers", {}))
        assert fired == expected, (case["id"], fired, expected)


def test_benchmark_shows_asking_beats_guessing(domain, db):
    engine = Engine(domain, db, OfflineDemoProvider())
    guess = run_eval(engine, "guess")["summary"]
    ask = run_eval(engine, "ask")["summary"]
    assert ask["accuracy"] == 100.0 and ask["errors"] == 0
    assert guess["accuracy_on_clear"] == 100.0           # guessing is fine when nothing is vague...
    assert guess["accuracy_on_ambiguous"] == 0.0         # ...and wrong every time when something is
    assert ask["detection_recall"] == 100.0 and ask["false_alarm_rate"] == 0.0
    assert ask["empty_expected_results"] == 0


def test_offline_provider_refuses_unknown_questions():
    request = SQLRequest(question="Translate this poem", schema="", notes=(), today=TODAY)
    with pytest.raises(OfflineProviderError, match="sample questions"):
        OfflineDemoProvider().generate_sql(request)


def test_offline_provider_honours_resolutions(domain, db):
    engine = Engine(domain, db, OfflineDemoProvider())
    by = lambda choice: engine.ask("What is the most popular book?", lambda r: choice).rows  # noqa: E731
    assert by("loans") != by("rating") != by("borrowers")
