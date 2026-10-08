"""Companion-call speech metrics, baselines and flags (wellness signals, not diagnoses).

Transcript lines: {"speaker": "hugh"|"senior", "text": str, "t_ms": int}
For Hugh lines t_ms = when Hugh finished speaking (playback ended). For senior lines
t_ms = when the final transcription arrived (end of their utterance). So
  response_gap = senior.t_ms - previous hugh.t_ms  (thinking time + speaking time)
  latency     ~= response_gap - (words / 150 wpm)  (estimated thinking time)
  wpm         = senior words / total response_gap minutes ("effective speaking rate")
"""
import re
from statistics import mean

FILLERS = re.compile(r"\b(um+|uh+|erm+|hmm+|er|ah+|you know|i mean)\b", re.I)
PAUSE_MARK = re.compile(r"(\.\.\.|…|\[pause\])")

BASELINE_MIN_CALLS = 3
BASELINE_MAX_CALLS = 7


def compute(transcript: list[dict], recall: str = "n/a", mood: str = "neutral", repetition: bool = False) -> dict:
    words_total = 0
    gap_total_ms = 0
    latencies = []
    fillers = 0
    prev_hugh_t = None
    for line in transcript:
        if line.get("speaker") == "hugh":
            prev_hugh_t = line.get("t_ms", 0)
            continue
        if line.get("speaker") != "senior":
            continue
        text = line.get("text", "")
        words = len(text.split())
        words_total += words
        fillers += len(FILLERS.findall(text)) + len(PAUSE_MARK.findall(text))
        if prev_hugh_t is not None:
            gap = max(0, line.get("t_ms", 0) - prev_hugh_t)
            if gap > 0:
                gap_total_ms += gap
                latencies.append(max(0.0, gap - words / 150 * 60000))
            prev_hugh_t = None
    wpm = round(words_total / (gap_total_ms / 60000), 1) if gap_total_ms > 0 and words_total else None
    return {
        "wpm": wpm,
        "latency_ms": round(mean(latencies)) if latencies else None,
        "filler_rate": round(fillers / words_total * 100, 1) if words_total else None,
        "senior_words": words_total,
        "recall": recall,
        "mood": mood,
        "repetition": repetition,
    }


def baseline(history: list[dict]) -> dict:
    """history: metrics dicts of earlier calls, oldest first."""
    base = history[:BASELINE_MAX_CALLS]

    def avg(key):
        vals = [h[key] for h in base if h.get(key) is not None]
        return round(mean(vals), 1) if len(vals) >= BASELINE_MIN_CALLS else None

    return {"wpm": avg("wpm"), "latency_ms": avg("latency_ms"), "filler_rate": avg("filler_rate")}


def flags_for(current: dict, base: dict, recent: list[dict]) -> list[str]:
    """recent: metrics of the previous calls (newest last), not including current."""
    flags = []
    if base.get("wpm") and current.get("wpm") is not None and current["wpm"] < 0.75 * base["wpm"]:
        flags.append("slower_speech")
    if base.get("latency_ms") and current.get("latency_ms") is not None and current["latency_ms"] > 1.5 * base["latency_ms"]:
        flags.append("longer_pauses")
    if base.get("filler_rate") and current.get("filler_rate") is not None and current["filler_rate"] > 1.5 * max(base["filler_rate"], 1.0):
        flags.append("more_hesitation")
    last = recent[-1] if recent else {}
    if current.get("recall") == "none" and last.get("recall") == "none":
        flags.append("recall_difficulty")
    if current.get("repetition") and last.get("repetition"):
        flags.append("repetition")
    if current.get("mood") == "low" and len(recent) >= 2 and all(r.get("mood") == "low" for r in recent[-2:]):
        flags.append("low_mood")
    return flags


FLAG_TEXT = {
    "slower_speech": "spoke more slowly than usual",
    "longer_pauses": "took longer than usual to answer",
    "more_hesitation": "hesitated more than usual",
    "recall_difficulty": "found it hard to recall recent things two days in a row",
    "repetition": "repeated stories two days in a row",
    "low_mood": "seemed low for a few days",
}


def describe(flags: list[str], name: str) -> str:
    parts = [FLAG_TEXT[f] for f in flags if f in FLAG_TEXT]
    if not parts:
        return ""
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Hugh noticed {name} {joined}. You may want to check in with them."
