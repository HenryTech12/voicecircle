import { useEffect, useRef } from "react";
import type { Line } from "../lib/api";

const who: Record<string, string> = { caller: "Practice caller", senior: "", system: "VoiceCircle", hugh: "Hugh" };

export function Transcript({ lines, seniorName, callerName }: { lines: Line[]; seniorName: string; callerName?: string }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const el = end.current;
    const box = el?.closest(".overflow-y-auto");
    if (el && box) box.scrollTop = box.scrollHeight;
  }, [lines.length]);
  if (!lines.length) return <p className="text-lg text-muted">Nothing said yet.</p>;
  return (
    <ol className="space-y-3" aria-label="Call transcript">
      {lines.map((l, i) => {
        const mine = l.speaker === "senior";
        const name = mine ? seniorName : l.speaker === "caller" ? `${callerName ?? "Caller"} (cloned voice)` : who[l.speaker];
        return (
          <li key={i} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-lg ${
                mine ? "bg-brand text-white" : l.speaker === "system" ? "border-2 border-dashed border-line bg-bg text-ink" : "bg-bg text-ink"
              }`}
            >
              <p className={`text-sm font-bold ${mine ? "text-white/85" : "text-muted"}`}>{name}</p>
              <p>{l.text}</p>
            </div>
          </li>
        );
      })}
      <li ref={end} aria-hidden className="h-0" />
    </ol>
  );
}
