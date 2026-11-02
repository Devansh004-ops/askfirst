import json

import pytest

from askfirst import load_domain
from askfirst.detect import detect


def fired(domain, question):
    return [r.id for r in detect(question, domain.rules)]


@pytest.mark.parametrize("question,expected", [
    ("What is the most popular book?", ["book_ranking"]),
    ("Which books are the best?", ["book_ranking"]),
    ("Show me the top titles", ["book_ranking"]),
    ("Who is our top member?", ["member_ranking"]),
    ("Show me recent loans", ["recent_window"]),
    ("How many active members do we have?", ["active_members"]),
    ("Which member has been most active recently?", ["member_ranking", "recent_window"]),   # two terms, both found
    ("What are the best books and who are the top members?", ["book_ranking", "member_ranking"]),
])
def test_vague_questions_fire_the_right_rules(domain, question, expected):
    assert fired(domain, question) == expected


@pytest.mark.parametrize("question", [
    "What are the top 3 books by number of loans?",        # the metric is stated
    "Which books have the highest rating?",                # 'rating' pins it down
    "What is the most borrowed book?",                     # 'borrowed'
    "Show loans from the last 14 days",                    # explicit window
    "How many loans were made this month?",                # explicit period
    "How many books are currently on loan?",
    "List the titles of books published after 2015.",
    "Which loans are overdue?",
    "How many members belong to the Riverside branch?",
    "Who has borrowed the most books?",
    "Which member has the most loans?",
])
def test_precise_or_plain_questions_do_not_fire(domain, question):
    assert fired(domain, question) == []


def test_matching_is_case_insensitive(domain):
    assert fired(domain, "WHAT IS THE MOST POPULAR BOOK") == ["book_ranking"]


def test_each_rule_fires_at_most_once(domain):
    assert fired(domain, "popular books, favourite books, best books") == ["book_ranking"]


def test_rule_without_patterns_never_matches_text():
    from askfirst.model import Interpretation, Rule
    rule = Rule("x", "t", "q?", (Interpretation("a", "A", "h"), Interpretation("b", "B", "h")))
    assert not rule.matches("anything at all")


# ---- domain pack validation --------------------------------------------------
def make_pack(tmp_path, rules, glossary=None):
    (tmp_path / "domain.json").write_text(json.dumps({"name": "t"}))
    (tmp_path / "schema.sql").write_text("CREATE TABLE a (x INTEGER);")
    (tmp_path / "rules.json").write_text(json.dumps(rules))
    if glossary is not None:
        (tmp_path / "glossary.json").write_text(json.dumps(glossary))
    return tmp_path


OK_RULE = {"id": "r", "term": "t", "question": "q?", "when_all": ["x"],
           "options": [{"id": "a", "label": "A", "hint": "h", "default": True}, {"id": "b", "label": "B", "hint": "h"}]}


def test_custom_pack_loads(tmp_path):
    d = load_domain(make_pack(tmp_path, [OK_RULE]))
    assert d.rule("r").default_option.id == "a" and d.schema_sql.startswith("CREATE TABLE")


def test_rule_needs_two_options(tmp_path):
    bad = {**OK_RULE, "options": OK_RULE["options"][:1]}
    with pytest.raises(ValueError, match="two options"):
        load_domain(make_pack(tmp_path, [bad]))


def test_rule_cannot_have_two_defaults(tmp_path):
    bad = {**OK_RULE, "options": [{**o, "default": True} for o in OK_RULE["options"]]}
    with pytest.raises(ValueError, match="more than one default"):
        load_domain(make_pack(tmp_path, [bad]))


def test_duplicate_option_ids_rejected(tmp_path):
    bad = {**OK_RULE, "options": [OK_RULE["options"][0], {**OK_RULE["options"][1], "id": "a"}]}
    with pytest.raises(ValueError, match="duplicate"):
        load_domain(make_pack(tmp_path, [bad]))


def test_glossary_must_reference_real_rules_and_options(tmp_path):
    with pytest.raises(ValueError, match="not a defined"):
        load_domain(make_pack(tmp_path, [OK_RULE], {"r": "zzz"}))
    with pytest.raises(ValueError, match="not a defined"):
        load_domain(make_pack(tmp_path, [OK_RULE], {"nope": "a"}))


def test_not_a_pack(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_domain(tmp_path)


def test_every_builtin_rule_has_exactly_one_default_and_three_options(domain):
    for rule in domain.rules:
        assert sum(o.default for o in rule.options) == 1, rule.id
        assert len(rule.options) == 3, rule.id
