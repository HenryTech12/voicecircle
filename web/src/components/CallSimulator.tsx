import { PhoneOff, Send } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { Button, Input, useToast } from "./ui";

/** Mock mode only: lets you play the senior's side of a simulated call from the browser. */
export function CallSimulator({ callId, suggestions, onChange }: { callId: string; suggestions: string[]; onChange: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function send(t: string) {
    if (!t.trim()) return;
    setBusy(true);
    try {
      await api.simSay(callId, t.trim());
      setText("");
      onChange();
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function hangup() {
    setBusy(true);
    try {
      await api.simHangup(callId);
      onChange();
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl2 border-2 border-warn/40 bg-warn-soft p-4">
      <p className="text-base font-bold text-warn">Call simulator (demo mode)</p>
      <p className="mb-3 text-base text-ink">Type what the senior says, as if you were answering the phone.</p>
      <div className="mb-3 flex flex-wrap gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            disabled={busy}
            onClick={() => send(s)}
            className="min-h-[44px] rounded-full border-2 border-line bg-white px-4 text-base font-bold hover:border-brand focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand disabled:opacity-50"
          >
            “{s}”
          </button>
        ))}
      </div>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <label htmlFor={`sim-${callId}`} className="sr-only">What the senior says</label>
        <Input id={`sim-${callId}`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Say something…" />
        <Button type="submit" loading={busy} disabled={!text.trim()}>
          <Send className="h-5 w-5" aria-hidden /> Say
        </Button>
        <Button type="button" variant="danger" onClick={hangup} disabled={busy}>
          <PhoneOff className="h-5 w-5" aria-hidden /> Hang up
        </Button>
      </form>
    </div>
  );
}
