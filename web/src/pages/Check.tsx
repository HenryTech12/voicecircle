import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileAudio, HelpCircle, Loader2, ShieldAlert, ShieldCheck, UserX } from "lucide-react";
import { useRef, useState } from "react";
import { useCircle } from "../components/Layout";
import { Badge, Button, Card, Empty, ErrorBox, Field, PageHeader, Select, Spinner } from "../components/ui";
import { api, type Detection } from "../lib/api";
import { VERDICT, dateTime } from "../lib/format";

const ICON = { real: ShieldCheck, fake: ShieldAlert, not_them: UserX, unsure: HelpCircle };
const ADVICE = {
  real: "It still makes sense to call them back on their usual number before sending any money.",
  fake: "Don't send money or share details. Hang up and call the person on the number you already have for them.",
  not_them: "Don't send money or share details. Call the person on their usual number to check.",
  unsure: "Treat this call with care. Call the person back on their usual number before doing anything.",
};

export function VerdictPanel({ d }: { d: Detection }) {
  if (d.status === "processing")
    return (
      <div role="status" className="flex items-center gap-3 rounded-xl2 bg-brand-soft p-6 text-xl font-bold text-brand-dark">
        <Loader2 className="h-7 w-7 animate-spin" aria-hidden /> Checking the recording…
      </div>
    );
  if (d.status === "failed" || !d.verdict) return <ErrorBox error={new Error(d.error || "We couldn't check this recording. Try a clearer or longer clip.")} />;
  const v = VERDICT[d.verdict];
  const Icon = ICON[d.verdict];
  const bg = v.tone === "good" ? "bg-good-soft text-good" : v.tone === "bad" ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn";
  return (
    <div className={`rounded-xl2 p-6 ${bg}`} role="status">
      <div className="flex items-center gap-4">
        <Icon className="h-14 w-14 shrink-0" aria-hidden />
        <div>
          <p className="font-display text-4xl font-bold leading-tight sm:text-5xl">{v.label}</p>
          <p className="mt-1 text-lg font-bold text-ink">Claimed to be {d.claimed_member_name}</p>
        </div>
      </div>
      <p className="mt-4 text-xl text-ink">{d.explanation}</p>
      <p className="mt-3 text-lg text-ink"><span className="font-bold">What to do: </span>{ADVICE[d.verdict]}</p>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-base text-ink">
        <div className="rounded-xl bg-white/70 p-3">
          <dt className="text-muted">AI-generated likelihood</dt>
          <dd className="text-xl font-bold">{d.synthetic_score === null ? "—" : `${Math.round(d.synthetic_score * 100)}%`}</dd>
        </div>
        <div className="rounded-xl bg-white/70 p-3">
          <dt className="text-muted">Match with {d.claimed_member_name}</dt>
          <dd className="text-xl font-bold">{d.speaker_match_score === null ? "—" : `${Math.round(d.speaker_match_score * 100)}%`}</dd>
        </div>
      </dl>
    </div>
  );
}

export default function Check() {
  const { circle, contacts, circleId, query } = useCircle();
  const enrolled = contacts.filter((c) => c.voice_status === "enrolled");
  const [claimed, setClaimed] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const history = useQuery({ queryKey: ["detections", circleId], queryFn: () => api.detections(circleId), enabled: !!circleId });
  const current = useQuery({
    queryKey: ["detection", currentId],
    queryFn: () => api.detection(currentId!),
    enabled: !!currentId,
    refetchInterval: (q) => (q.state.data?.status === "processing" ? 1200 : false),
  });
  const submit = useMutation({
    mutationFn: () => api.checkRecording(circleId, file!, claimed || enrolled[0].id),
    onSuccess: (d) => {
      setCurrentId(d.id);
      qc.setQueryData(["detection", d.id], d);
      qc.invalidateQueries({ queryKey: ["detections", circleId] });
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      qc.invalidateQueries({ queryKey: ["alerts", circleId] });
    },
  });

  if (query.isLoading || !circle) return <Spinner />;
  if (!enrolled.length) return <Empty title="Record a trusted voice first" body="We compare suspicious recordings with a family member's enrolled voice." />;

  return (
    <div>
      <PageHeader title="Check a call" subtitle="Got a worrying call from someone who sounded like family? Upload the recording and we'll tell you if the voice looks real." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
            <Field label="Who did the caller say they were?" htmlFor="claimed">
              <Select id="claimed" value={claimed || enrolled[0].id} onChange={(e) => setClaimed(e.target.value)}>
                {enrolled.map((c) => <option key={c.id} value={c.id}>{c.display_name}{c.relationship ? ` (${c.relationship})` : ""}</option>)}
              </Select>
            </Field>
            <Field label="The recording" hint="Voicemail or call recording. MP3, WAV, M4A, OGG or WebM, up to 20 MB." htmlFor="rec">
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
                className="flex min-h-[120px] w-full flex-col items-center justify-center gap-2 rounded-xl2 border-2 border-dashed border-line bg-bg p-6 text-lg hover:border-brand focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand"
              >
                <FileAudio className="h-8 w-8 text-brand" aria-hidden />
                {file ? <span className="font-bold">{file.name}</span> : <span><span className="font-bold text-brand">Choose a file</span> or drop it here</span>}
              </button>
              <input id="rec" ref={inputRef} type="file" accept="audio/*,.m4a,.mp3,.wav,.ogg,.webm" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
            <ErrorBox error={submit.error} />
            <Button type="submit" size="lg" className="w-full" disabled={!file} loading={submit.isPending}>Check this voice</Button>
          </form>
        </Card>
        <div>
          {current.data ? (
            <VerdictPanel d={current.data} />
          ) : (
            <Card className="h-full">
              <h2 className="text-2xl font-bold">How it works</h2>
              <ol className="mt-3 list-decimal space-y-2 pl-6 text-lg">
                <li>We check whether the voice was made by AI.</li>
                <li>We compare it with the family member's real voice.</li>
                <li>You get a clear answer in plain words, usually within 20 seconds.</li>
              </ol>
              <p className="mt-4 text-base text-muted">No check is perfect. When in doubt, always call back on a number you already know.</p>
            </Card>
          )}
        </div>
      </div>

      <section className="mt-10">
        <h2 className="mb-4 text-2xl font-bold">Past checks</h2>
        {history.data?.length === 0 && <p className="text-lg text-muted">No recordings checked yet.</p>}
        <ul className="space-y-3">
          {history.data?.map((d) => (
            <li key={d.id}>
              <button className="w-full rounded-xl2 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand" onClick={() => setCurrentId(d.id)}>
                <Card className="flex flex-wrap items-center justify-between gap-3 hover:border-brand">
                  <div>
                    <p className="text-lg font-bold">{d.original_filename || "Recording"}</p>
                    <p className="text-base text-muted">Claimed to be {d.claimed_member_name} · {dateTime(d.created_at)}</p>
                  </div>
                  {d.verdict ? <Badge tone={VERDICT[d.verdict].tone}>{VERDICT[d.verdict].label}</Badge> : <Badge>{d.status}</Badge>}
                </Card>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
