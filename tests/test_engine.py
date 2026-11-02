import pytest

from askfirst.model import Interpretation, Rule
from conftest import FakeProvider

POPULAR = "SELECT title FROM books LIMIT 1"


def test_clear_question_is_never_asked_about(make_engine):
    asked = []
    engine = make_engine(FakeProvider("SELECT COUNT(*) FROM loans WHERE returned_on IS NULL"))
    ans = engine.ask("How many books are currently on loan?", lambda rule: asked.append(rule) or 1)
    assert ans.ok and asked == [] and ans.resolutions == [] and ans.rows[0][0] > 0


def test_vague_question_asks_and_passes_the_chosen_meaning_to_the_provider(make_engine):
    provider = FakeProvider(POPULAR)
    ans = make_engine(provider).ask("What is the most popular book?", lambda rule: "rating")
    request = provider.requests[0]
    assert ans.asked == ["book_ranking"]
    assert [r.interpretation.id for r in request.resolutions] == ["rating"]
    assert "AVG(rating)" in request.resolutions[0].interpretation.hint
    assert request.question == "What is the most popular book?"       # the question itself is left untouched


def test_request_carries_schema_notes_and_the_reference_date(make_engine):
    provider = FakeProvider("SELECT 1")
    make_engine(provider).ask("anything", None)
    request = provider.requests[0]
    assert "Table loans:" in request.schema and any("overdue" in n for n in request.notes)
    assert request.today == "2026-01-15"                               # read from the database, not the clock


def test_explicit_today_overrides_the_database(make_engine):
    assert make_engine(FakeProvider(), today="2030-02-03").today == "2030-02-03"


def test_declining_to_answer_proceeds_with_a_reported_assumption(make_engine):
    ans = make_engine(FakeProvider(POPULAR)).ask("Show me recent loans", None)
    assert ans.ok and [r.source for r in ans.resolutions] == ["assumed"]
    assert ans.assumptions[0].interpretation.id == "30d" and ans.asked == []


def test_glossary_prevents_asking(make_engine):
    asked = []
    engine = make_engine(FakeProvider(POPULAR), glossary={"book_ranking": "borrowers"})
    ans = engine.ask("What is the best book?", lambda rule: asked.append(rule))
    assert asked == [] and ans.resolutions[0].source == "glossary"


def test_failing_query_is_repaired_once_using_the_real_sqlite_error(make_engine):
    provider = FakeProvider("SELECT titel FROM books", "SELECT title FROM books LIMIT 2")
    ans = make_engine(provider).ask("List some titles", None)
    assert ans.ok and ans.repairs == 1 and len(ans.rows) == 2
    second = provider.requests[1]
    assert second.previous_sql == "SELECT titel FROM books" and "titel" in second.error


def test_gives_up_after_max_repairs(make_engine):
    provider = FakeProvider("SELECT a FROM books", "SELECT b FROM books")
    ans = make_engine(provider, max_repairs=1).ask("x", None)
    assert not ans.ok and ans.repairs == 1 and "no such column: b" in ans.error
    assert len(provider.requests) == 2


def test_no_repairs_when_disabled(make_engine):
    provider = FakeProvider("SELECT a FROM books", "SELECT title FROM books")
    ans = make_engine(provider, max_repairs=0).ask("x", None)
    assert not ans.ok and len(provider.requests) == 1


@pytest.mark.parametrize("sql", ["DROP TABLE loans", "SELECT 1; DELETE FROM loans", "SELECT * FROM sqlite_master"])
def test_refused_queries_are_reported_and_never_repaired(make_engine, sql):
    provider = FakeProvider(sql, "SELECT 1")
    ans = make_engine(provider).ask("x", None)
    assert ans.error.startswith("Blocked by the sandbox") and ans.repairs == 0 and len(provider.requests) == 1


def test_provider_failure_is_reported_not_raised(make_engine):
    provider = FakeProvider(RuntimeError("API key missing"), "SELECT 1")
    ans = make_engine(provider).ask("x", None)
    assert "SQL generation failed: API key missing" in ans.error and len(provider.requests) == 1


def test_probe_finds_a_term_the_rules_miss(make_engine):
    probe = Rule("probe:big", "big", "How big?", (Interpretation("opt1", "Many pages", "h1", True),
                                                   Interpretation("opt2", "Many loans", "h2")))
    provider = FakeProvider("SELECT 1", probe_rule=probe)
    ans = make_engine(provider, probe=True).ask("Which are the big books?", lambda rule: 2)
    assert ans.asked == ["probe:big"] and provider.requests[0].resolutions[0].interpretation.id == "opt2"


def test_probe_is_off_by_default_and_never_blocks(make_engine):
    class Exploding(FakeProvider):
        def probe(self, question, schema):
            raise RuntimeError("boom")

    assert make_engine(Exploding("SELECT 1"), probe=False).ask("odd question", None).ok
    assert make_engine(Exploding("SELECT 1"), probe=True).ask("odd question", None).ok


def test_remember_makes_the_second_question_silent(make_engine, tmp_path):
    from askfirst import PreferenceStore
    engine = make_engine(FakeProvider(POPULAR, POPULAR), prefs=PreferenceStore(tmp_path / "p.json"), remember=True)
    first = engine.ask("What is the best book?", lambda rule: 3)
    second = engine.ask("What is the most popular book?", lambda rule: pytest.fail("asked twice"))
    assert first.asked == ["book_ranking"] and second.asked == []
    assert second.resolutions[0].source == "preference" and second.resolutions[0].interpretation.id == "rating"
