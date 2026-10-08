import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Lightbulb, PhoneCall, PhoneOff } from "lucide-react";
import { useEffect, useState } from "react";
import { CallSimulator } from "../components/CallSimulator";
import { useCircle } from "../components/Layout";
import { Transcript } from "../components/Transcript";
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, useToast } from "../components/ui";
import { api, type Difficulty, type PracticeCall } from "../lib/api";
import { useAuth } from "../lib/auth";
import { DIFFICULTY_TEXT, OUTCOME, dateTime, duration } from "../lib/format";

const ACTIVE = ["queued", "dialing", "in_progress"];
const SUGGESTIONS = ["Who is this really?", "Let me call you back on your own number.", "Okay, how much do you need?", "Hmm, I'm not sure about this."];
const STATUS_TEXT: Record<string, string> = {
  queued: "Getting ready…", dialing: "Ringing their phone…", in_progress: "Call in progress", completed: "Finished",
  failed: "Couldn't complete", no_answer: "No answer", cancelled: "Cancelled",
};

function Choice({ selected, onClick, title, hint, disabled }: { selected: boolean; onClick: () => void; title: string; hint: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onClick}
      className={`min-h-[72px] rounded-xl border-2 p-4 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand disabled:opacity-50 ${
        selected ? "border-brand bg-brand-soft" : "border-line bg-white hover:border-brand/60"
      }`}
    >
      <span className="flex items-center gap-2 text-lg font-bold">
        {selected && <CheckCircle2 className="h-5 w-5 text-brand" aria-hidden />} {title}
      </span>
      <span className="mt-1 block text-base text-muted">{hint}</span>
    </button>
  );
}

export function OutcomeCard({ call, seniorName }: { call: PracticeCall; seniorName: string }) {
  if (!call.outcome) return null;
  const o = OUTCOME[call.outcome];
  const tone = o.tone;
  return (
    <div className={`rounded-xl2 p-5 ${tone === "good" ? "bg-good-soft" : tone === "warn" ? "bg-warn-soft" : "bg-bad-soft"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className={`font-display text-3xl font-bold ${tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : "text-bad"}`}>
          {tone === "good" ? "Well done: " : tone === "warn" ? "Close call: " : "Needs practice: "}
          {o.label}
        </p>
        {call.score !== null && <p className="text-2xl font-bold">Score {call.score}/100</p>}
      </div>
      <p className="mt-2 text-lg">{o.sentence(seniorName)}</p>
      {call.safety_stop && <p className="mt-2 text-base font-bold">The call stopped automatically when real personal details were mentioned. Those details were not saved.</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {!!call.feedback?.did_well?.length && (
          <div>
            <p className="font-bold">What went well</p>
            <ul className="mt-1 list-disc pl-5 text-lg">{call.feedback.did_well.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
        )}
        {!!call.feedback?.practice_next?.length && (
          <div>
            <p className="flex items-center gap-1 font-bold"><Lightbulb className="h-5 w-5" aria-hidden /> Practice next</p>
            <ul className="mt-1 list-disc pl-5 text-lg">{call.feedback.practice_next.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Training() {
  const { circle, senior, contacts, circleId, query } = useCircle();
  const { config } = useAuth();
  const enrolled = contacts.filter((c) => c.voice_status === "enrolled");
  const [voiceId, setVoiceId] = useState<string>("");
  const [scenario, setScenario] = useState("grandchild_in_trouble");
  const [difficulty, setDifficulty] = useState<Difficulty>("easy");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const history = useQuery({
    queryKey: ["practice", circleId],
    queryFn: () => api.practiceCalls(circleId),
    enabled: !!circleId,
  });
  const runningFromHistory = history.data?.find((c) => ACTIVE.includes(c.status) && !c.scheduled_for);
  const liveId = activeId ?? runningFromHistory?.id ?? null;
  const live = useQuery({
    queryKey: ["practice-call", liveId],
    queryFn: () => api.practiceCall(liveId!),
    enabled: !!liveId,
    refetchInterval: (q) => (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 1200),
  });

  const liveStatus = live.data?.status;
  useEffect(() => {
    if (liveStatus && !ACTIVE.includes(liveStatus)) {
      qc.invalidateQueries({ queryKey: ["practice", circleId] });
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      qc.invalidateQueries({ queryKey: ["alerts", circleId] });
    }
  }, [liveStatus, qc, circleId]);

  const start = useMutation({
    mutationFn: () =>
      api.startPractice(circleId, { senior_member_id: senior!.id, voice_member_id: voiceId || enrolled[0].id, scenario, difficulty }),
    onSuccess: (c) => {
      setActiveId(c.id);
      qc.invalidateQueries({ queryKey: ["practice", circleId] });
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelPractice(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["practice-call", liveId] });
      qc.invalidateQueries({ queryKey: ["practice", circleId] });
    },
  });

  if (query.isLoading || !circle) return <Spinner />;
  if (!senior) return <Empty title="Add your loved one first" body="Go to Voices and add the person you're protecting." />;
  if (!enrolled.length) return <Empty title="Record a trusted voice first" body="Practice calls use a family member's voice, so at least one voice needs to be enrolled." />;

  const callerFor = (id: string) => contacts.find((c) => c.id === id)?.display_name ?? "Caller";
  const liveCall = live.data;
  const isLive = liveCall && ACTIVE.includes(liveCall.status);
  const selectedVoice = voiceId || enrolled[0].id;

  return (
    <div>
      <PageHeader title="Practice calls" subtitle={`A safe pretend scam call to ${senior.display_name}, in a family member's voice. Every call ends by explaining it was practice.`} />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <h2 className="text-2xl font-bold">Set up a call</h2>
          <div className="mt-5 space-y-6">
            <fieldset>
              <legend className="mb-2 text-lg font-bold">Whose voice?</legend>
              <div role="radiogroup" className="grid gap-2">
                {enrolled.map((c) => (
                  <Choice key={c.id} selected={selectedVoice === c.id} onClick={() => setVoiceId(c.id)} title={c.display_name} hint={c.relationship || "Trusted contact"} disabled={!!isLive} />
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-lg font-bold">What kind of scam?</legend>
              <div role="radiogroup" className="grid gap-2">
                {scenarios.data?.map((s) => (
                  <Choice key={s.key} selected={scenario === s.key} onClick={() => setScenario(s.key)} title={s.title} hint={s.description} disabled={!!isLive} />
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-lg font-bold">How hard?</legend>
              <div role="radiogroup" className="grid grid-cols-3 gap-2">
                {(["easy", "medium", "hard"] as Difficulty[]).map((d) => (
                  <Choice key={d} selected={difficulty === d} onClick={() => setDifficulty(d)} title={DIFFICULTY_TEXT[d].label} hint={DIFFICULTY_TEXT[d].hint} disabled={!!isLive} />
                ))}
              </div>
            </fieldset>
            <Button size="lg" className="w-full" loading={start.isPending} disabled={!!isLive} onClick={() => start.mutate()}>
              <PhoneCall className="h-6 w-6" aria-hidden /> Call {senior.display_name} now
            </Button>
          </div>
        </Card>

        <Card className="lg:col-span-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-2xl font-bold">{isLive ? "Live call" : liveCall ? "Latest call" : "Live call"}</h2>
            {liveCall && (
              <Badge tone={isLive ? "brand" : liveCall.status === "completed" ? "good" : "neutral"}>
                {isLive && <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-brand" aria-hidden />}
                {STATUS_TEXT[liveCall.status]}
              </Badge>
            )}
          </div>
          {!liveCall ? (
            <p className="mt-4 text-lg text-muted">Start a call and you'll see the conversation here as it happens.</p>
          ) : (
            <div className="mt-5 space-y-5" aria-live="polite">
              <p className="text-base text-muted">
                {callerFor(liveCall.voice_member_id)}'s voice · {scenarios.data?.find((s) => s.key === liveCall.scenario)?.title} · {DIFFICULTY_TEXT[liveCall.difficulty].label}
              </p>
              <OutcomeCard call={liveCall} seniorName={senior.display_name} />
              {liveCall.feedback?.error && <ErrorBox error={new Error(liveCall.feedback.error)} />}
              <div className="max-h-[420px] overflow-y-auto pr-1">
                <Transcript lines={liveCall.transcript} seniorName={senior.display_name} callerName={callerFor(liveCall.voice_member_id)} />
              </div>
              {isLive && config?.mock_providers && liveCall.status === "in_progress" && (
                <CallSimulator callId={liveCall.id} suggestions={SUGGESTIONS} onChange={() => live.refetch()} />
              )}
              {isLive && (
                <Button variant="secondary" onClick={() => cancel.mutate(liveCall.id)} loading={cancel.isPending}>
                  <PhoneOff className="h-5 w-5" aria-hidden /> End call now
                </Button>
              )}
            </div>
          )}
        </Card>
      </div>

      <section className="mt-10">
        <h2 className="mb-4 text-2xl font-bold">History</h2>
        {history.isLoading && <Spinner />}
        {history.data?.length === 0 && <p className="text-lg text-muted">No practice calls yet.</p>}
        <ul className="space-y-3">
          {history.data?.map((c) => {
            const o = c.outcome ? OUTCOME[c.outcome] : null;
            const open = openId === c.id;
            return (
              <li key={c.id}>
                <Card className="p-0 sm:p-0">
                  <button
                    className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl2 p-5 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand"
                    aria-expanded={open}
                    onClick={() => setOpenId(open ? null : c.id)}
                  >
                    <div>
                      <p className="text-lg font-bold">{scenarios.data?.find((s) => s.key === c.scenario)?.title ?? c.scenario} · {DIFFICULTY_TEXT[c.difficulty].label}</p>
                      <p className="text-base text-muted">{dateTime(c.created_at)} · {callerFor(c.voice_member_id)}'s voice {c.duration_seconds ? `· ${duration(c.duration_seconds)}` : ""}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      {o ? <Badge tone={o.tone}>{o.label}</Badge> : <Badge>{STATUS_TEXT[c.status]}</Badge>}
                      {c.score !== null && <span className="text-xl font-bold">{c.score}</span>}
                    </div>
                  </button>
                  {open && (
                    <div className="space-y-4 border-t border-line p-5">
                      <OutcomeCard call={c} seniorName={senior.display_name} />
                      <Transcript lines={c.transcript} seniorName={senior.display_name} callerName={callerFor(c.voice_member_id)} />
                    </div>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
