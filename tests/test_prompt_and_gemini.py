import json
from types import SimpleNamespace

import pytest

from askfirst.model import Interpretation, Resolution, SQLRequest
from askfirst.prompt import SYSTEM, build_user_prompt, extract_sql
from askfirst.providers import make_provider
from askfirst.providers.gemini import GeminiProvider, parse_probe


def request(**kw):
    base = dict(question="What is the best book?", schema="Table books:\n  title text", notes=("Note one",),
                today="2026-01-15")
    base.update(kw)
    return SQLRequest(**base)


def test_extract_sql_handles_bare_fenced_and_chatty_replies():
    assert extract_sql("SELECT 1") == "SELECT 1"
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql("```\nSELECT 2;\n```") == "SELECT 2;"
    assert extract_sql("Here you go:\n```SQLite\nSELECT a\nFROM t\n```\nHope that helps!") == "SELECT a\nFROM t"
    assert extract_sql("```SELECT 3```") == "SELECT 3"
    assert extract_sql("```sql\nSELECT 4") == "SELECT 4"          # a fence the model forgot to close
    assert extract_sql(None) == "" and extract_sql("   ") == ""


def test_a_language_tag_is_removed_only_when_it_is_a_known_one():
    from askfirst.prompt import strip_code_fence
    assert strip_code_fence("```json\n{}\n```", ("json",)) == "{}"
    assert strip_code_fence("```yaml\nkey: 1\n```", ("json",)) == "yaml\nkey: 1"


def test_prompt_contains_date_schema_notes_question_and_interpretations():
    res = Resolution("book_ranking", "popular", Interpretation("rating", "Rating", "Rank by AVG(rating)."), "user")
    text = build_user_prompt(request(resolutions=(res,)))
    for fragment in ("TODAY: 2026-01-15", "Table books:", "- Note one", '- "popular": Rank by AVG(rating).',
                     "QUESTION: What is the best book?"):
        assert fragment in text
    assert "PREVIOUS SQL" not in text


def test_repair_prompt_only_when_both_sql_and_error_are_given():
    assert "PREVIOUS SQL" not in build_user_prompt(request(previous_sql="SELECT x"))
    text = build_user_prompt(request(previous_sql="SELECT x", error="no such column: x"))
    assert "PREVIOUS SQL:\nSELECT x" in text and "SQLITE ERROR:\nno such column: x" in text


def test_system_prompt_forbids_the_wall_clock():
    assert "never use 'now'" in SYSTEM.lower() or "Never use 'now'" in SYSTEM


# ---- probe parsing -----------------------------------------------------------
GOOD = {"term": "big", "question": "How big?",
        "options": [{"label": "Many loans", "hint": "h1"}, {"label": "Many pages", "hint": "h2"}]}


def test_parse_probe_builds_a_rule():
    rule = parse_probe(json.dumps(GOOD))
    assert rule.id == "probe:big" and rule.default_option.id == "opt1" and len(rule.options) == 2


def test_parse_probe_accepts_fenced_json_and_caps_options_at_four():
    many = {**GOOD, "options": [{"label": f"L{i}", "hint": "h"} for i in range(9)]}
    assert len(parse_probe("```json\n" + json.dumps(many) + "\n```").options) == 4


@pytest.mark.parametrize("bad", [
    "null", "", "not json", "[]", json.dumps({**GOOD, "options": GOOD["options"][:1]}),
    json.dumps({**GOOD, "term": " "}), json.dumps({**GOOD, "options": "x"}),
    json.dumps({**GOOD, "options": [{"label": "same", "hint": "h"}, {"label": "same", "hint": "h2"}]}),
    json.dumps({"term": "x"}),
])
def test_parse_probe_rejects_anything_unusable(bad):
    assert parse_probe(bad) is None


# ---- provider ------------------------------------------------------------------
class FakeClient:
    """Stands in for google.genai.Client: remembers each call, replies with fixed text."""

    def __init__(self, text):
        self.calls = []
        self._text = text
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self._text)


def test_gemini_provider_extracts_sql_from_a_fenced_reply():
    pytest.importorskip("google.genai")
    client = FakeClient("```sql\nSELECT 1\n```")
    sql = GeminiProvider(model="m", client=client).generate_sql(request())
    assert sql == "SELECT 1"
    call = client.calls[0]
    assert call["model"] == "m" and "QUESTION: What is the best book?" in call["contents"]
    assert call["config"].temperature == 0.0


def test_gemini_probe_failure_never_raises():
    pytest.importorskip("google.genai")

    class Broken:
        models = SimpleNamespace(generate_content=lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))

    assert GeminiProvider(client=Broken()).probe("q", "schema") is None


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider()._get_client()


def test_make_provider():
    assert make_provider("offline").name == "offline"
    assert make_provider("gemini").name == "gemini"
    with pytest.raises(ValueError, match="Unknown provider"):
        make_provider("nope")
