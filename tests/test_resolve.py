import json

from askfirst.model import (SOURCE_ASSUMED, SOURCE_GLOSSARY, SOURCE_PREFERENCE, SOURCE_USER, Interpretation, Rule)
from askfirst.resolve import PreferenceStore, interpret_reply, resolve

RULE = Rule("r", "term", "Which?", (Interpretation("a", "Option A", "ha", default=True),
                                     Interpretation("b", "Option B", "hb"),
                                     Interpretation("c", "Option C", "hc")))


def run(chooser=None, glossary=None, prefs=None, remember=False):
    prefs = prefs or PreferenceStore()
    res, asked = resolve([RULE], glossary=glossary or {}, prefs=prefs, chooser=chooser, remember=remember)
    return res[0], asked, prefs


def test_user_answer_by_number():
    res, asked, _ = run(lambda r: 2)
    assert (res.interpretation.id, res.source, asked) == ("b", SOURCE_USER, ["r"])


def test_user_answer_by_numeric_string_and_by_id():
    assert run(lambda r: "3")[0].interpretation.id == "c"
    assert run(lambda r: "b")[0].interpretation.id == "b"


def test_free_text_becomes_a_custom_meaning():
    res, _, _ = run(lambda r: "only books from before 2000")
    assert res.interpretation.id == "custom" and "only books from before 2000" in res.interpretation.hint
    assert res.source == SOURCE_USER


def test_declining_or_invalid_answers_fall_back_to_a_reported_default():
    for reply in (None, "", "   ", 0, 9, "9"):
        res, asked, _ = run(lambda r, reply=reply: reply)
        assert (res.interpretation.id, res.source) == ("a", SOURCE_ASSUMED), reply
        assert asked == ["r"]                      # we did ask; the answer just was not usable


def test_no_chooser_means_assumption_without_asking():
    res, asked, _ = run(None)
    assert res.source == SOURCE_ASSUMED and asked == []


def test_glossary_beats_asking():
    res, asked, _ = run(lambda r: 3, glossary={"r": "b"})
    assert (res.interpretation.id, res.source, asked) == ("b", SOURCE_GLOSSARY, [])


def test_saved_preference_beats_glossary_and_asking():
    prefs = PreferenceStore()
    prefs.set("r", "c")
    res, asked, _ = run(lambda r: 1, glossary={"r": "b"}, prefs=prefs)
    assert (res.interpretation.id, res.source, asked) == ("c", SOURCE_PREFERENCE, [])


def test_stale_preference_for_a_removed_option_is_ignored():
    prefs = PreferenceStore()
    prefs.set("r", "gone")
    res, asked, _ = run(lambda r: 2, prefs=prefs)
    assert res.source == SOURCE_USER and asked == ["r"]


def test_remember_saves_the_choice_but_not_custom_text(tmp_path):
    path = tmp_path / "prefs.json"
    run(lambda r: 2, prefs=PreferenceStore(path), remember=True)
    assert json.loads(path.read_text()) == {"r": "b"}
    path2 = tmp_path / "prefs2.json"
    run(lambda r: "my own meaning", prefs=PreferenceStore(path2), remember=True)
    assert not path2.exists()


def test_second_question_uses_the_remembered_choice(tmp_path):
    path = tmp_path / "prefs.json"
    run(lambda r: 3, prefs=PreferenceStore(path), remember=True)
    res, asked, _ = run(lambda r: 1, prefs=PreferenceStore(path))
    assert (res.interpretation.id, res.source, asked) == ("c", SOURCE_PREFERENCE, [])


def test_corrupt_preference_file_never_blocks(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    assert PreferenceStore(path).get("r") is None


def test_forget(tmp_path):
    store = PreferenceStore(tmp_path / "p.json")
    store.set("r", "a"); store.set("s", "b")
    store.forget("r")
    assert store.get("r") is None and store.get("s") == "b"
    store.forget()
    assert store.get("s") is None


def test_interpret_reply_unit():
    assert interpret_reply(RULE, 1).id == "a"
    assert interpret_reply(RULE, 4) is None
    assert interpret_reply(RULE, None) is None
