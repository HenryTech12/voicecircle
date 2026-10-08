"""Unit tests for pure logic: scoring, safety guard, metrics, client_state, scenarios."""
import pytest

from app.services import llm, metrics, scenarios, twilio


def T(*pairs):
    return [{"speaker": s, "text": t, "t_ms": i * 1000} for i, (s, t) in enumerate(pairs)]


@pytest.mark.parametrize(
    "lines,hung_up,expected",
    [
        ([("caller", "Hi"), ("senior", "Who is this?")], True, "hung_up_early"),
        ([("caller", "Hi"), ("senior", "Let me call your mother first.")], False, "verified"),
        ([("caller", "Hi"), ("senior", "No, I won't do that.")], False, "refused"),
        ([("caller", "Hi"), ("senior", "How much do you need?")], False, "complied"),
        ([("caller", "Hi"), ("senior", "Where do I send it?"), ("senior", "Wait, this is a scam.")], True, "hesitated"),
        ([("caller", "Hi"), ("senior", "Oh?"), ("senior", "Really?"), ("senior", "Hmm.")], False, "hesitated"),
        ([("caller", "Hi"), ("senior", "Oh no, what happened?")], True, "hung_up_early"),
    ],
)
def test_classify_fallback(lines, hung_up, expected):
    out = llm.classify_fallback(T(*lines), hung_up, False)
    assert out["outcome"] == expected
    assert out["score"] == llm.SCORES[expected]
    assert out["did_well"] and out["practice_next"]


def test_safety_stop_always_complied():
    assert llm.classify_fallback(T(("senior", "hello")), True, True)["outcome"] == "complied"


@pytest.mark.parametrize(
    "text,sensitive",
    [
        ("my card number is", True),
        ("4111 1111 1111", True),
        ("four one one one two", True),
        ("my PIN", True),
        ("I'm 82 years old", False),
        ("call me at 5", False),
        ("Hello dear, how are you?", False),
    ],
)
def test_is_sensitive(text, sensitive):
    assert llm.is_sensitive(text) is sensitive


def test_metrics_compute():
    tr = [
        {"speaker": "hugh", "text": "How are you?", "t_ms": 2000},
        {"speaker": "senior", "text": "I am fine thank you um", "t_ms": 5000},  # 6 words in 3 s
        {"speaker": "hugh", "text": "What did you do?", "t_ms": 8000},
        {"speaker": "senior", "text": "I went to the market... and bought peppers", "t_ms": 12000},
    ]
    m = metrics.compute(tr, "correct", "positive", False)
    assert m["senior_words"] == 14
    assert m["wpm"] == round(14 / (7000 / 60000), 1)
    assert m["filler_rate"] == round(2 / 14 * 100, 1)
    assert m["latency_ms"] is not None and m["recall"] == "correct"


def test_metrics_empty():
    m = metrics.compute([])
    assert m["wpm"] is None and m["latency_ms"] is None and m["filler_rate"] is None


def test_baseline_needs_three_calls():
    assert metrics.baseline([{"wpm": 100}, {"wpm": 110}])["wpm"] is None
    assert metrics.baseline([{"wpm": 100}, {"wpm": 110}, {"wpm": 120}])["wpm"] == 110


def test_flags():
    base = {"wpm": 120, "latency_ms": 1000, "filler_rate": 2}
    cur = {"wpm": 80, "latency_ms": 1600, "filler_rate": 5, "recall": "none", "mood": "low", "repetition": True}
    recent = [{"recall": "none", "mood": "low", "repetition": True}, {"recall": "none", "mood": "low", "repetition": True}]
    flags = metrics.flags_for(cur, base, recent)
    assert set(flags) == {"slower_speech", "longer_pauses", "more_hesitation", "recall_difficulty", "repetition", "low_mood"}
    assert metrics.flags_for({"wpm": 118, "latency_ms": 1000, "filler_rate": 2}, base, []) == []
    msg = metrics.describe(["slower_speech", "longer_pauses"], "Ada")
    assert msg.startswith("Hugh noticed Ada") and " and " in msg
    assert metrics.describe([], "Ada") == ""


def test_client_state_roundtrip():
    s = twilio.encode_state({"kind": "practice", "id": "abc"})
    assert twilio.decode_state(s) == {"kind": "practice", "id": "abc"}
    assert twilio.decode_state("%%%") == {} and twilio.decode_state(None) == {}


def test_scenarios_render():
    for key, sc in scenarios.SCENARIOS.items():
        for d in scenarios.DIFFICULTIES:
            line = scenarios.opener(key, d, "Ada", "Alex", ["the trip to Calabar"])
            assert "{" not in line and line
    hard = scenarios.scripted_line("grandchild_in_trouble", "hard", 2, "Ada", "Alex", ["the trip to Calabar"])
    assert "Calabar" in hard
    assert scenarios.scripted_line("grandchild_in_trouble", "easy", 99, "Ada", "Alex", []) is None


def test_summarize_fallback():
    tr = [
        {"speaker": "hugh", "text": "Hello", "t_ms": 0},
        {"speaker": "senior", "text": "I feel lonely today", "t_ms": 1000},
        {"speaker": "hugh", "text": "What did you have for breakfast this morning?", "t_ms": 2000},
        {"speaker": "senior", "text": "I can't remember", "t_ms": 3000},
    ]
    out = llm.summarize_fallback(tr, "What did you have for breakfast this morning?")
    assert out["mood"] == "low" and out["recall"] == "none"
