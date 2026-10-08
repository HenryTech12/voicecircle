import { Mic, RotateCcw, Square, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "./ui";

export interface Recording { blob: Blob; filename: string; seconds: number }

function pickMime() {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  return types.find((t) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(t)) || "";
}

export function Recorder({ prompts, onReady }: { prompts: string[]; onReady: (r: Recording | null) => void }) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [promptIdx, setPromptIdx] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const raf = useRef<number>();
  const timer = useRef<number>();
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => stopAll(), []);

  function stopAll() {
    if (raf.current) cancelAnimationFrame(raf.current);
    if (timer.current) clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
  }

  async function start() {
    setError(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      stream.current = s;
      const mime = pickMime();
      const mr = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      mr.onstop = () => {
        const type = mr.mimeType || "audio/webm";
        const blob = new Blob(chunks, { type });
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        setUrl(URL.createObjectURL(blob));
        setState("done");
        onReady({ blob, filename: `voice-sample.${ext}`, seconds });
        stopAll();
      };
      // level meter
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(1, peak / 64));
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      setSeconds(0);
      timer.current = window.setInterval(() => setSeconds((x) => x + 1), 1000);
      mr.start();
      rec.current = mr;
      setState("recording");
      onReady(null);
    } catch {
      setError("We couldn't use your microphone. Allow microphone access in your browser, or upload a recording instead.");
    }
  }

  function stop() {
    rec.current?.stop();
  }

  function reset() {
    setState("idle");
    setUrl(null);
    setPromptIdx(0);
    setSeconds(0);
    onReady(null);
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setUrl(URL.createObjectURL(f));
    setState("done");
    onReady({ blob: f, filename: f.name, seconds: 0 });
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl2 bg-brand-soft p-5" aria-live="polite">
        <p className="text-base font-bold uppercase tracking-wide text-brand-dark">
          Read this out loud {state === "recording" ? `(${promptIdx + 1} of ${prompts.length})` : ""}
        </p>
        <p className="mt-2 font-display text-2xl leading-snug text-ink">“{prompts[promptIdx] ?? ""}”</p>
        {state === "recording" && (
          <Button
            variant="secondary"
            size="sm"
            className="mt-4"
            onClick={() => setPromptIdx((i) => Math.min(prompts.length - 1, i + 1))}
            disabled={promptIdx >= prompts.length - 1}
          >
            Next sentence
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-4">
        {state !== "recording" ? (
          <Button size="lg" onClick={start} aria-label={state === "done" ? "Record again" : "Start recording"}>
            <Mic className="h-6 w-6" aria-hidden /> {state === "done" ? "Record again" : "Start recording"}
          </Button>
        ) : (
          <Button size="lg" variant="danger" onClick={stop}>
            <Square className="h-6 w-6" aria-hidden /> Stop ({seconds}s)
          </Button>
        )}
        <Button variant="secondary" onClick={() => fileRef.current?.click()}>
          <Upload className="h-5 w-5" aria-hidden /> Upload a file instead
        </Button>
        <input ref={fileRef} type="file" accept="audio/*" className="sr-only" onChange={onFile} aria-label="Upload voice recording" />
        {state === "done" && (
          <Button variant="ghost" onClick={reset}>
            <RotateCcw className="h-5 w-5" aria-hidden /> Start over
          </Button>
        )}
      </div>

      {state === "recording" && (
        <div>
          <div className="h-4 w-full overflow-hidden rounded-full bg-bg" role="meter" aria-label="Microphone level" aria-valuenow={Math.round(level * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full bg-brand transition-[width] duration-75" style={{ width: `${Math.max(4, level * 100)}%` }} />
          </div>
          <p className="mt-2 text-base text-muted">
            {seconds < 30 ? `Keep going: about ${30 - seconds} more seconds is ideal.` : "Great, that's enough. Press Stop when you finish the sentence."}
          </p>
        </div>
      )}
      {url && state === "done" && (
        <div>
          <p className="mb-2 text-lg font-bold">Listen back</p>
          <audio controls src={url} className="w-full" />
        </div>
      )}
      {error && <p role="alert" className="text-lg font-bold text-bad">{error}</p>}
    </div>
  );
}
