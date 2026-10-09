"""LLM tasks with deterministic fallbacks (used in mock mode and when the LLM fails)."""
import json
import logging
import re

import httpx

from ..config import settings
from . import scenarios

log = logging.getLogger("voicecircle.llm")

# ------------------------------------------------------------------ keyword rules

COMPLY = [
    r"\bi'?ll send\b", r"\bi will send\b", r"\bi can send\b", r"\bwhere (do|should) i send\b",
    r"\bhow much\b", r"\bokay,? i'?ll (do|pay|buy)\b", r"\bi'?ll (pay|buy|transfer|wire)\b",
    r"\bgive me the (details|account)\b", r"\bwhat'?s the account\b", r"\bsend (it|the money) now\b",
    r"\bi'?ll go to the bank\b", r"\bread (you )?the numbers\b",
]
VERIFY = [
    r"\bcall (you|your \w+) back\b", r"\bcall your (mum|mom|mother|father|dad|wife|husband)\b",
    r"\bverify\b", r"\bprove\b", r"\bwho is this really\b", r"\bwhat'?s my\b", r"\bwhat is my\b",
    r"\blet me call\b", r"\bi'?ll call\b", r"\bcheck with\b", r"\bsecret word\b", r"\bcall .* first\b",
]
REFUSE = [
    r"^\s*no\b", r"\bno,? (thanks|thank you|i won'?t|way)\b", r"\bi said no\b", r"\bnot sending\b", r"\bi won'?t\b", r"\bscam\b", r"\bnot going to\b", r"\bi refuse\b",
    r"\bgoodbye\b", r"\bhang(ing)? up\b", r"\bdon'?t believe\b", r"\bstop calling\b",
]
DIGITS = re.compile(r"(\d[\s-]?){4,}")
SENSITIVE = re.compile(r"\b(card number|account number|pin|cvv|password|bank details|sort code)\b", re.I)
NUMBER_WORDS = re.compile(r"\b((zero|one|two|three|four|five|six|seven|eight|nine|oh)[\s,-]+){4,}", re.I)

SCORES = {"hung_up_early": 100, "verified": 90, "refused": 80, "hesitated": 50, "complied": 0}


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def is_sensitive(text: str) -> bool:
    """Senior is reading out digits / financial details -> stop the practice call now."""
    return bool(DIGITS.search(text) or NUMBER_WORDS.search(text) or SENSITIVE.search(text))


def stood_firm(transcript: list[dict], needed: int = 2) -> bool:
    """True once the senior has pushed back (verify/refuse) `needed` times and never complied."""
    senior = [t["text"] for t in transcript if t.get("speaker") == "senior"]
    if any(_any(COMPLY, x) for x in senior):
        return False
    return sum(1 for x in senior if _any(VERIFY, x) or _any(REFUSE, x)) >= needed


def classify_fallback(transcript: list[dict], hung_up_by_senior: bool, safety_stop: bool) -> dict:
    senior = [t["text"] for t in transcript if t.get("speaker") == "senior"]
    joined = " ".join(senior)
    complied_idx = next((i for i, s in enumerate(senior) if _any(COMPLY, s)), None)
    verify_idx = next((i for i, s in enumerate(senior) if _any(VERIFY, s)), None)
    refuse_idx = next((i for i, s in enumerate(senior) if _any(REFUSE, s)), None)

    if safety_stop:
        outcome = "complied"
    elif complied_idx is not None:
        later = [i for i in (verify_idx, refuse_idx) if i is not None and i > complied_idx]
        outcome = "hesitated" if later else "complied"
    elif verify_idx is not None:
        outcome = "verified"
    elif refuse_idx is not None:
        outcome = "refused"
    elif hung_up_by_senior and len(senior) <= 2:
        outcome = "hung_up_early"
    elif len(senior) >= 3:
        outcome = "hesitated"
    else:
        outcome = "refused" if hung_up_by_senior else "hesitated"

    did_well, practice = [], []
    if outcome in ("hung_up_early", "refused"):
        did_well.append("You didn't give in to the pressure.")
    if outcome == "verified" or verify_idx is not None:
        did_well.append("You asked to check who was really calling. That is the best move.")
    if outcome in ("hesitated", "complied"):
        practice.append("When someone asks for money urgently, hang up and call them back on a number you know.")
    if re.search(r"gift card|western union|transfer|wire", joined, re.I):
        practice.append("Family will never ask you to pay with gift cards or wire transfers in secret.")
    if not did_well:
        did_well.append("You stayed calm and listened.")
    if not practice:
        practice.append("Keep it up: a secret family code word makes checking even easier.")
    return {"outcome": outcome, "score": SCORES[outcome], "did_well": did_well, "practice_next": practice}


# ------------------------------------------------------------------ LLM transport


def _llm_enabled() -> bool:
    return not settings.MOCK_PROVIDERS and bool(settings.LLM_API_KEY)


OPENAI_COMPATIBLE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5",
}


def effective_model() -> str:
    """The configured model, unless it clearly belongs to another provider (e.g. gpt-* left over after
    switching to Groq), in which case the provider's default is used instead of failing with a 404."""
    provider, model = settings.LLM_PROVIDER, (settings.LLM_MODEL or "").strip()
    wrong = (
        not model
        or (provider != "openai" and model.startswith(("gpt-", "o1", "o3", "o4")))
        or (provider != "anthropic" and model.startswith("claude"))
    )
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"]) if wrong else model


def _check(r: httpx.Response) -> None:
    if r.is_success:
        return
    raise RuntimeError(f"{settings.LLM_PROVIDER} API {r.status_code} (model={effective_model()}): {r.text[:300]}")


async def complete_json(system: str, user: str, max_tokens: int = 400) -> dict:
    if settings.LLM_PROVIDER == "anthropic":
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.LLM_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": effective_model(),
                    "max_tokens": max_tokens,
                    "system": system + "\nRespond with a single JSON object only.",
                    "messages": [{"role": "user", "content": user}],
                },
            )
            _check(r)
            text = "".join(b.get("text", "") for b in r.json()["content"])
    else:
        # OpenAI and Groq share the same chat-completions API; only the base URL differs.
        base = settings.LLM_BASE_URL or OPENAI_COMPATIBLE_URLS.get(settings.LLM_PROVIDER, OPENAI_COMPATIBLE_URLS["openai"])
        # Twilio abandons a webhook after ~15s, so fail fast and let the scripted fallback answer instead.
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json={
                    "model": effective_model(),
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system + "\nRespond with a single JSON object."},
                        {"role": "user", "content": user},
                    ],
                },
            )
            _check(r)
            text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _fmt(transcript: list[dict]) -> str:
    return "\n".join(f"{t['speaker'].upper()}: {t['text']}" for t in transcript) or "(no conversation yet)"


# ------------------------------------------------------------------ scam turns


async def next_scam_line(
    scenario: str, difficulty: str, turn: int, senior: str, contact: str, relationship: str | None,
    facts: list[str], transcript: list[dict],
) -> dict:
    """Return {"line": str, "end": bool}."""
    scripted = scenarios.scripted_line(scenario, difficulty, turn, senior, contact, facts)
    if difficulty == "easy" or not _llm_enabled():
        return {"line": scripted, "end": scripted is None}
    sc = scenarios.SCENARIOS[scenario]
    system = (
        f"You are role-playing a SCAMMER in a consented, family-arranged SAFETY TRAINING call for an older adult. "
        f"You impersonate {contact} ({relationship or 'a relative'}) calling {senior}. Scenario: {sc['description']} "
        f"Goal of the scam: get them to {sc['ask']}. Difficulty: {difficulty}. "
        + ("Be natural, warm, believable; handle pushback calmly; use urgency and secrecy subtly. "
           if difficulty == "hard" else "Use clear urgency and secrecy. ")
        + (f"Known true details you may mention once: {facts}. " if facts and difficulty == "hard" else "")
        + "Rules: max 35 words, spoken style, no stage directions. NEVER ask for card numbers, PINs or passwords; "
        "only ask for a transfer or gift cards in general terms. If the senior clearly refuses, asks to verify, "
        "says they'll call someone back, or says it's a scam, set end=true. "
        'Output JSON: {"line": "<what you say next>", "end": false}'
    )
    try:
        out = await complete_json(system, f"Conversation so far:\n{_fmt(transcript)}\n\nYour next line:")
        line = str(out.get("line") or "").strip()
        return {"line": line or scripted, "end": bool(out.get("end")) or not (line or scripted)}
    except Exception as e:
        log.warning("LLM next_scam_line failed, using script: %s", e)
        return {"line": scripted, "end": scripted is None}


async def classify_outcome(transcript: list[dict], hung_up_by_senior: bool, safety_stop: bool) -> dict:
    fallback = classify_fallback(transcript, hung_up_by_senior, safety_stop)
    if not _llm_enabled() or safety_stop or not transcript:
        return fallback
    system = (
        "You grade how an older adult handled a PRACTICE scam call. Outcomes: "
        "hung_up_early (hung up quickly before engaging), verified (asked a verification question or said they'd "
        "call back on a known number), refused (clearly said no), hesitated (engaged/asked questions past the money "
        "ask, or agreed then changed their mind), complied (agreed to pay or started giving details). "
        f"The senior {'hung up' if hung_up_by_senior else 'did not hang up'}. "
        'Output JSON: {"outcome": "...", "did_well": ["short kind sentence"], '
        '"practice_next": ["short kind sentence"]}. Use warm, simple language.'
    )
    try:
        out = await complete_json(system, _fmt(transcript))
        outcome = out.get("outcome")
        if outcome not in SCORES:
            return fallback
        return {
            "outcome": outcome,
            "score": SCORES[outcome],
            "did_well": out.get("did_well") or fallback["did_well"],
            "practice_next": out.get("practice_next") or fallback["practice_next"],
        }
    except Exception as e:
        log.warning("LLM classify failed, using fallback: %s", e)
        return fallback


# ------------------------------------------------------------------ companion (Hugh)

HUGH_SCRIPT = [
    "Hello {senior}, it's Hugh, your VoiceCircle friend. How are you feeling today?",
    "That's lovely to hear. What have you been up to today? Have you eaten?",
    "{recall}",
    "Thank you for chatting with me, {senior}. Take care, and I'll call you again tomorrow. Goodbye!",
]


def hugh_system(senior: str, previous: list[str], recall_question: str) -> str:
    prev = " | ".join(previous) if previous else "This is one of the first calls."
    return (
        f"You are Hugh, a warm, patient, slow-paced companion who calls {senior} every day for a short chat. "
        "Speak in short, simple sentences. Ask about their day, meals, family, hobbies. "
        f"Recent call summaries: {prev}. During the call, ask this gentle recall question once: '{recall_question}'. "
        "Never give medical advice, never mention tests, memory checks, dementia or diagnoses. "
        "Keep the call to about 3 minutes and end warmly."
    )


async def companion_reply(senior: str, turn: int, recall_question: str, previous: list[str], transcript: list[dict]) -> dict:
    scripted = None
    if turn < len(HUGH_SCRIPT):
        scripted = HUGH_SCRIPT[turn].format(senior=senior, recall=recall_question)
    end_scripted = turn >= len(HUGH_SCRIPT) - 1
    if not _llm_enabled():
        return {"line": scripted, "end": end_scripted}
    system = hugh_system(senior, previous, recall_question) + (
        f' This is turn {turn + 1}. After about 4 turns, say goodbye and set end=true. '
        'Output JSON: {"line": "<what Hugh says>", "end": false}'
    )
    try:
        out = await complete_json(system, f"Conversation so far:\n{_fmt(transcript)}\n\nHugh's next line:")
        line = str(out.get("line") or "").strip() or scripted
        return {"line": line, "end": bool(out.get("end")) or turn >= 6}
    except Exception as e:
        log.warning("LLM companion_reply failed: %s", e)
        return {"line": scripted, "end": end_scripted}


def recall_question_for(previous_summary: str | None) -> str:
    if previous_summary:
        return f"Last time we spoke, you told me about this: {previous_summary[:120]}. How did that go?"
    return "What did you have for breakfast this morning?"


NEG_MOOD = re.compile(r"\b(sad|lonely|tired|pain|sick|worried|alone|bad day|not good|unwell)\b", re.I)
POS_MOOD = re.compile(r"\b(good|great|fine|lovely|happy|wonderful|well|nice)\b", re.I)
CANT_RECALL = re.compile(r"\b(don'?t remember|can'?t remember|forgot|no idea|not sure|i don'?t know)\b", re.I)


def summarize_fallback(transcript: list[dict], recall_question: str | None) -> dict:
    senior_lines = [t["text"] for t in transcript if t.get("speaker") == "senior"]
    text = " ".join(senior_lines)
    mood = "low" if NEG_MOOD.search(text) else "positive" if POS_MOOD.search(text) else "neutral"
    # recall answer = first senior line after the recall question was asked
    recall = "n/a"
    if recall_question:
        asked = False
        for t in transcript:
            if t.get("speaker") == "hugh" and recall_question[:30] in t["text"]:
                asked = True
                continue
            if asked and t.get("speaker") == "senior":
                words = len(t["text"].split())
                recall = "none" if CANT_RECALL.search(t["text"]) else "correct" if words >= 5 else "partial"
                break
    lowered = [s.lower().strip() for s in senior_lines]
    repetition = len(lowered) != len(set(lowered)) and len(lowered) > 1
    summary = (senior_lines[1] if len(senior_lines) > 1 else (senior_lines[0] if senior_lines else "Short call"))[:160]
    return {"summary": summary, "recall": recall, "mood": mood, "repetition": repetition}


async def summarize_companion(transcript: list[dict], recall_question: str | None) -> dict:
    fallback = summarize_fallback(transcript, recall_question)
    if not _llm_enabled() or not transcript:
        return fallback
    system = (
        "Summarize a friendly daily check-in call with an older adult. Output JSON: "
        '{"summary": "<one sentence about what they did or talked about>", '
        '"recall": "correct|partial|none|n/a" (how well they answered the recall question: '
        f"'{recall_question}'), "
        '"mood": "positive|neutral|low", "repetition": true|false (did they repeat the same story/question)}'
    )
    try:
        out = await complete_json(system, _fmt(transcript))
        return {
            "summary": str(out.get("summary") or fallback["summary"])[:300],
            "recall": out.get("recall") if out.get("recall") in ("correct", "partial", "none", "n/a") else fallback["recall"],
            "mood": out.get("mood") if out.get("mood") in ("positive", "neutral", "low") else fallback["mood"],
            "repetition": bool(out.get("repetition")),
        }
    except Exception as e:
        log.warning("LLM summarize failed: %s", e)
        return fallback
