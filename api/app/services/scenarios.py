"""Practice scam scenarios. Easy lines are fixed; medium/hard are LLM-driven personas
(the scripted lines are used in mock mode and as a fallback)."""

SCENARIOS: dict[str, dict] = {
    "grandchild_in_trouble": {
        "title": "Grandchild in trouble",
        "description": "A family member calls in a panic, needs money urgently and asks you to keep it secret.",
        "ask": "send money by bank transfer or gift cards",
        "lines": {
            "easy": [
                "Hi {senior}, it's me, {contact}! I'm in big trouble and I need money right now.",
                "Please don't tell anyone. Just buy gift cards and read me the numbers, quickly.",
                "I can't explain, there's no time. You have to do it now or something bad will happen.",
                "Please, {senior}, I'm begging you. Gift cards, today.",
            ],
            "medium": [
                "Hey {senior}, it's {contact}. Sorry to call like this, I'm in a bit of a mess.",
                "I lost my wallet and my phone, I'm calling from a friend's phone. I need to pay a fine today.",
                "Could you send me some money by transfer? I'll pay you back next week, I promise.",
                "Please don't mention it to Mum yet, I'm embarrassed. I'll explain everything later.",
            ],
            "hard": [
                "{senior}? It's {contact}. Can you hear me okay? The line here is terrible.",
                "I'm so sorry, I didn't want to worry you. I'm alright, but I'm in a real situation.",
                "I need to sort something out before tonight and the bank has frozen my card. {fact_line}",
                "If you can do a transfer I'll give you the details. Please keep this between us for now, okay?",
            ],
        },
    },
    "car_accident_bail": {
        "title": "Car accident, needs bail",
        "description": "A relative says they were in a car accident and need money for bail or the other driver.",
        "ask": "pay bail or the other driver",
        "lines": {
            "easy": [
                "{senior}, it's {contact}! I crashed the car and the police took me. I need bail money now!",
                "The lawyer says send cash today. Don't call anyone, just send it.",
                "Hurry, they will lock me up if you don't pay in the next hour.",
                "Please just send it, I'll explain later.",
            ],
            "medium": [
                "Hi {senior}, it's {contact}. I'm okay, but I was in an accident this morning.",
                "The other driver is threatening to press charges unless I pay for the damage today.",
                "I don't have enough in my account. Could you help me with the payment?",
                "I'll text you the account details. Please don't tell the family, they'll panic.",
            ],
            "hard": [
                "{senior}, it's {contact}. First, I'm fine, nobody is badly hurt. {fact_line}",
                "There was a small accident and the officer said we can settle it without court if I pay today.",
                "The lawyer is here with me, he can explain. It's just the fee to close the case.",
                "I'd rather Mum didn't find out until I sort it. Can you help me with the transfer?",
            ],
        },
    },
    "stuck_abroad": {
        "title": "Stuck abroad",
        "description": "A relative says they are stuck overseas after losing their passport and money.",
        "ask": "wire money for a flight or hotel",
        "lines": {
            "easy": [
                "{senior}! It's {contact}. I'm stuck abroad, somebody stole everything!",
                "Wire me money right now through Western Union. Don't ask questions.",
                "Hurry, I have no money for the hotel tonight.",
                "Please, today, I'm begging you.",
            ],
            "medium": [
                "Hi {senior}, it's {contact}. I'm on a short trip and my bag with my passport got stolen.",
                "The embassy says it will take a few days and I can't pay the hotel.",
                "Could you send me money for the hotel and a new ticket? I'll pay you back.",
                "Please keep it quiet for now, I don't want everyone worrying.",
            ],
            "hard": [
                "{senior}? It's {contact}, I'm calling from the hotel phone. {fact_line}",
                "I'm safe, but my wallet and passport were stolen at the airport and my cards are blocked.",
                "The embassy appointment is on Monday. I just need to cover the hotel until then.",
                "I'll send the details by text. Can you do it today? And please, just between us.",
            ],
        },
    },
}

DIFFICULTIES = ["easy", "medium", "hard"]


def render(line: str, senior: str, contact: str, facts: list[str]) -> str:
    fact_line = f"Remember {facts[0]}? Anyway." if facts else ""
    return " ".join(line.format(senior=senior, contact=contact, fact_line=fact_line).split())


def opener(scenario: str, difficulty: str, senior: str, contact: str, facts: list[str]) -> str:
    return render(SCENARIOS[scenario]["lines"][difficulty][0], senior, contact, facts)


def scripted_line(scenario: str, difficulty: str, turn: int, senior: str, contact: str, facts: list[str]) -> str | None:
    lines = SCENARIOS[scenario]["lines"][difficulty]
    if turn < len(lines):
        return render(lines[turn], senior, contact, facts)
    return None


DISCLOSURE = (
    "This was a VoiceCircle practice call arranged by your family. It was not really {contact}. "
    "Real family will never mind if you hang up and call them back on a number you know. Goodbye for now."
)
