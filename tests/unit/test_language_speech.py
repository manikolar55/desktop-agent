from voice import language as L


def test_shorten_keeps_whole_sentences():
    text = "First sentence here. Second sentence is a bit longer than the first one. " * 5
    out = L.shorten_for_speech(text, limit=100)
    assert len(out) <= 100 and out.endswith(".")


def test_shorten_leaves_short_text_alone():
    assert L.shorten_for_speech("Task completed.") == "Task completed."


def test_shorten_single_long_sentence_is_cut():
    assert len(L.shorten_for_speech("word " * 100, limit=50)) <= 50


def test_unclear_is_passed_through(monkeypatch):
    monkeypatch.setattr(L, "_complete", lambda s, u, n: "LANG: Urdu\nENGLISH: UNCLEAR")
    assert L.to_english("garbled", "ur", refine=True) == ("UNCLEAR", "ur")
