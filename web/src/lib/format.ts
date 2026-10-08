import type { Outcome, Verdict } from "./api";

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  const days = Math.floor(diff / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function duration(sec: number | null | undefined): string {
  if (!sec && sec !== 0) return "";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m ? `${m} min ${s} s` : `${s} s`;
}

export const OUTCOME: Record<Outcome, { label: string; tone: "good" | "warn" | "bad"; sentence: (n: string) => string }> = {
  hung_up_early: { label: "Hung up quickly", tone: "good", sentence: (n) => `${n} hung up before the caller could apply pressure.` },
  verified: { label: "Checked who was calling", tone: "good", sentence: (n) => `${n} asked to check who was really calling.` },
  refused: { label: "Said no", tone: "good", sentence: (n) => `${n} refused to send money.` },
  hesitated: { label: "Nearly went along", tone: "warn", sentence: (n) => `${n} engaged with the money request before stopping.` },
  complied: { label: "Went along with it", tone: "bad", sentence: (n) => `${n} agreed to send money. More practice will help.` },
};

export const VERDICT: Record<Verdict, { label: string; tone: "good" | "bad" | "warn" }> = {
  real: { label: "Looks REAL", tone: "good" },
  fake: { label: "Looks FAKE", tone: "bad" },
  not_them: { label: "NOT the person they claimed", tone: "bad" },
  unsure: { label: "Not sure", tone: "warn" },
};

export const DIFFICULTY_TEXT = {
  easy: { label: "Easy", hint: "Obvious warning signs" },
  medium: { label: "Medium", hint: "More natural, some pressure" },
  hard: { label: "Hard", hint: "Very convincing, subtle pressure" },
} as const;

export const FLAG_TEXT: Record<string, string> = {
  slower_speech: "Speaking more slowly",
  longer_pauses: "Longer pauses before answering",
  more_hesitation: "More hesitation",
  recall_difficulty: "Harder to recall recent things",
  repetition: "Repeating stories",
  low_mood: "Seems low",
};

export function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

export function toE164(country: string, local: string): string {
  const digits = local.replace(/\D/g, "").replace(/^0+/, "");
  return digits ? `${country}${digits}` : "";
}
