from voice import language as L


def test_script_detection():
    assert L.script_of("Open Chrome") == "latin"
    assert L.script_of("کروم کھولو") == "arabic"
    assert L.script_of("ਕਰੋਮ ਖੋਲ੍ਹੋ") == "gurmukhi"


def test_text_language():
    assert L.detect_text_language("open youtube") == "en"
    assert L.detect_text_language("یوٹیوب کھولو") == "ur"
    assert L.detect_text_language("یوٹیوب کھولو", hint="pa") == "pa"
    assert L.detect_text_language("ਯੂਟਿਊਬ ਖੋਲ੍ਹੋ") == "pa"


def test_roman_urdu():
    assert L.detect_text_language("Chrome kholo") == "ur"
    assert L.detect_text_language("mujhe screen dikhao") == "ur"
    assert L.detect_text_language("open the settings window") == "en"


def test_voice_hint_matches_only_same_text():
    L.note_voice("abc", "pa")
    assert L.voice_hint("abc") == "pa"
    assert L.voice_hint("other") is None


def test_reply_language_state():
    L.set_reply_language("ur")
    assert L.get_reply_language() == "ur"
    L.set_reply_language("xx")
    assert L.get_reply_language() == "en"


def test_translation_failure_paths(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(L, "_complete", boom)
    assert L.to_english("کروم کھولو", "ur") == ("کروم کھولو", "ur")
    assert L.from_english("Task completed.", "ur") is None
    assert L.from_english("hello", "en") == "hello"


def test_to_english_parses_and_refines_language(monkeypatch):
    monkeypatch.setattr(L, "_complete", lambda s, u, n: "LANG: Punjabi\nENGLISH: Open YouTube")
    assert L.to_english("x", "ur", refine=True) == ("Open YouTube", "pa")
    assert L.to_english("x", "ur", refine=False) == ("Open YouTube", "ur")


def test_latin_text_uses_voice_hint():
    assert L.detect_text_language("youtube kolo ati gani labbo", hint="pa") == "pa"
    assert L.detect_text_language("open youtube", hint="en") == "en"


def test_translation_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(L, "_complete", lambda s, u, n: calls.append(u) or "ترجمہ")
    L._translation_cache.clear()
    assert L.from_english("Done.", "ur") == "ترجمہ"
    assert L.from_english("Done.", "ur") == "ترجمہ"
    assert len(calls) == 1
