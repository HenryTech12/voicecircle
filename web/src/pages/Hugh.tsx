import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PhoneCall } from "lucide-react";
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CallSimulator } from "../components/CallSimulator";
import { useCircle } from "../components/Layout";
import { Transcript } from "../components/Transcript";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, PageHeader, Spinner, useToast } from "../components/ui";
import { api, type Member, type TrendPoint } from "../lib/api";
import { useAuth } from "../lib/auth";
import { FLAG_TEXT, dateTime, duration, shortDate } from "../lib/format";

const ACTIVE = ["queued", "dialing", "in_progress"];
const SUGGESTIONS = ["I'm doing well, thank you.", "I watered my tomatoes and called my sister.", "Um... I can't quite remember.", "Goodbye Hugh, talk tomorrow."];

function Settings({ senior, circleId }: { senior: Member; circleId: string }) {
  const [time, setTime] = useState(senior.companion_call_time ?? "09:00");
  const [enabled, setEnabled] = useState(senior.companion_enabled);
  const [facts, setFacts] = useState(senior.personal_facts.join("\n"));
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => {
    setTime(senior.companion_call_time ?? "09:00");
    setEnabled(senior.companion_enabled);
    setFacts(senior.personal_facts.join("\n"));
  }, [senior]);
  const save = useMutation({
    mutationFn: () =>
      api.updateMember(senior.id, {
        companion_call_time: time,
        companion_enabled: enabled,
        personal_facts: facts.split("\n").map((f) => f.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      toast("Hugh's settings saved");
    },
  });
  return (
    <Card>
      <h2 className="text-2xl font-bold">Settings</h2>
      <form className="mt-4 space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className="flex cursor-pointer items-center gap-3 text-lg font-bold">
          <input type="checkbox" className="h-6 w-6 accent-brand" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Daily calls on
        </label>
        <Field label="Call time" hint={`In ${senior.display_name}'s time zone (${senior.timezone})`} htmlFor="htime">
          <Input id="htime" type="time" value={time} onChange={(e) => setTime(e.target.value)} disabled={!enabled} />
        </Field>
        <Field label="Things Hugh can chat about" hint="One per line, e.g. 'Grows tomatoes', 'Sister Funmi lives in Ibadan'" htmlFor="facts">
          <textarea
            id="facts"
            rows={4}
            value={facts}
            onChange={(e) => setFacts(e.target.value)}
            className="w-full rounded-xl border-2 border-line bg-white px-4 py-3 text-lg focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/20"
          />
        </Field>
        <ErrorBox error={save.error} />
        <Button type="submit" loading={save.isPending}>Save</Button>
      </form>
    </Card>
  );
}

function TrendChart({ title, points, dataKey, baseline, unit, betterLow }: { title: string; points: TrendPoint[]; dataKey: "wpm" | "latency_ms" | "filler_rate"; baseline: number | null | undefined; unit: string; betterLow?: boolean }) {
  const data = points.map((p) => ({ ...p, label: shortDate(p.date), value: p[dataKey] === null ? null : dataKey === "filler_rate" ? Math.round((p[dataKey] as number) * 10) / 10 : Math.round(p[dataKey] as number) }));
  const base = baseline == null ? null : dataKey === "filler_rate" ? Math.round(baseline * 10) / 10 : Math.round(baseline);
  const last = data.filter((d) => d.value !== null).at(-1)?.value ?? null;
  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold">{title}</h3>
        <p className="text-base text-muted">
          Latest <span className="font-bold text-ink">{last ?? "—"}{unit}</span>{base !== null && <> · usual {base}{unit}</>}
        </p>
      </div>
      <div className="mt-3 h-48" role="img" aria-label={`${title} over the last ${points.length} days. Latest ${last ?? "unknown"}${unit}, usual ${base ?? "unknown"}${unit}. ${betterLow ? "Lower is better." : "Higher is better."}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#ECE8DF" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 13, fill: "#5E5B53" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 13, fill: "#5E5B53" }} tickLine={false} axisLine={false} width={56} />
            <Tooltip formatter={(v) => [`${v}${unit}`, title]} contentStyle={{ fontSize: 15, borderRadius: 12 }} />
            {base !== null && <ReferenceLine y={base} stroke="#8A4B0F" strokeDasharray="6 4" label={{ value: "usual", position: "insideTopRight", fill: "#8A4B0F", fontSize: 13 }} />}
            <Line type="monotone" dataKey="value" stroke="#0E5C61" strokeWidth={3} dot={{ r: 4, fill: "#0E5C61" }} connectNulls isAnimationActive />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export default function Hugh() {
  const { circle, senior, circleId, query } = useCircle();
  const { config } = useAuth();
  const [liveId, setLiveId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const sid = senior?.id ?? "";

  const calls = useQuery({ queryKey: ["companion", sid], queryFn: () => api.companionCalls(sid), enabled: !!sid });
  const trends = useQuery({ queryKey: ["trends", sid], queryFn: () => api.trends(sid, 14), enabled: !!sid });
  const running = calls.data?.find((c) => ACTIVE.includes(c.status));
  const currentId = liveId ?? running?.id ?? null;
  const live = useQuery({
    queryKey: ["companion-call", currentId],
    queryFn: () => api.companionCall(currentId!),
    enabled: !!currentId,
    refetchInterval: (q) => (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 1200),
  });
  const isLive = !!live.data && ACTIVE.includes(live.data.status);
  useEffect(() => {
    if (live.data && !ACTIVE.includes(live.data.status)) {
      qc.invalidateQueries({ queryKey: ["companion", sid] });
      qc.invalidateQueries({ queryKey: ["trends", sid] });
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
    }
  }, [live.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const callNow = useMutation({
    mutationFn: () => api.callHugh(sid),
    onSuccess: (c) => {
      setLiveId(c.id);
      qc.invalidateQueries({ queryKey: ["companion", sid] });
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (query.isLoading || !circle) return <Spinner />;
  if (!senior) return <Empty title="Add your loved one first" body="Hugh needs a name and phone number to call." />;
  const t = trends.data;

  return (
    <div>
      <PageHeader
        title="Hugh, the daily companion"
        subtitle={`Hugh calls ${senior.display_name} for a short friendly chat and quietly notices changes in how they speak and remember.`}
        action={
          <Button size="lg" onClick={() => callNow.mutate()} loading={callNow.isPending} disabled={isLive}>
            <PhoneCall className="h-6 w-6" aria-hidden /> Have Hugh call now
          </Button>
        }
      />

      {t && t.flags.length > 0 && (
        <Card className="mb-6 border-2 border-warn/40 bg-warn-soft">
          <p className="text-lg font-bold text-warn">Hugh noticed some changes recently</p>
          <ul className="mt-2 flex flex-wrap gap-2">{t.flags.map((f) => <li key={f}><Badge tone="warn">{FLAG_TEXT[f] ?? f}</Badge></li>)}</ul>
          <p className="mt-3 text-base">This isn't a diagnosis. It's a nudge to check in with {senior.display_name}.</p>
        </Card>
      )}

      {live.data && (isLive || liveId) && (
        <Card className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-2xl font-bold">{isLive ? "Hugh is on the phone" : "Call finished"}</h2>
            <Badge tone={isLive ? "brand" : "good"}>{isLive ? "Live" : live.data.status}</Badge>
          </div>
          <div className="mt-4 space-y-4" aria-live="polite">
            {live.data.summary && <p className="rounded-xl bg-bg p-4 text-lg">{live.data.summary}</p>}
            <div className="max-h-[380px] overflow-y-auto pr-1">
              <Transcript lines={live.data.transcript} seniorName={senior.display_name} />
            </div>
            {isLive && config?.mock_providers && live.data.status === "in_progress" && (
              <CallSimulator callId={live.data.id} suggestions={SUGGESTIONS} onChange={() => live.refetch()} />
            )}
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <h2 className="text-2xl font-bold">Last 14 days</h2>
          {trends.isLoading && <Spinner />}
          {t && t.points.length === 0 && <Empty title="No calls yet" body="Trends appear after Hugh's first few calls." />}
          {t && t.points.length > 0 && (
            <>
              <TrendChart title="Speaking pace" points={t.points} dataKey="wpm" baseline={t.baseline.wpm} unit=" wpm" />
              <TrendChart title="Time to answer" points={t.points} dataKey="latency_ms" baseline={t.baseline.latency_ms} unit=" ms" betterLow />
              <TrendChart title="Filler words (um, uh) per 100 words" points={t.points} dataKey="filler_rate" baseline={t.baseline.filler_rate} unit="" betterLow />
            </>
          )}
        </div>
        <Settings senior={senior} circleId={circleId} />
      </div>

      <section className="mt-10">
        <h2 className="mb-4 text-2xl font-bold">Calls</h2>
        {calls.data?.length === 0 && <p className="text-lg text-muted">No calls yet.</p>}
        <ul className="space-y-3">
          {calls.data?.map((c) => {
            const open = openId === c.id;
            return (
              <li key={c.id}>
                <Card className="p-0 sm:p-0">
                  <button className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl2 p-5 text-left focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand" aria-expanded={open} onClick={() => setOpenId(open ? null : c.id)}>
                    <div className="min-w-0 flex-1">
                      <p className="text-lg font-bold">{dateTime(c.started_at || c.created_at)}{c.duration_seconds ? ` · ${duration(c.duration_seconds)}` : ""}</p>
                      <p className="text-base text-muted">{c.summary || (ACTIVE.includes(c.status) ? "In progress…" : c.status)}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {c.flags.length ? c.flags.map((f) => <Badge key={f} tone="warn">{FLAG_TEXT[f] ?? f}</Badge>) : c.status === "completed" && <Badge tone="good">All usual</Badge>}
                    </div>
                  </button>
                  {open && (
                    <div className="space-y-3 border-t border-line p-5">
                      {c.metrics && (
                        <p className="text-base text-muted">
                          Fillers {c.metrics.filler_rate ?? "—"} per 100 words · Pace {c.metrics.wpm ?? "—"} wpm · answers in {c.metrics.latency_ms ?? "—"} ms · recall: {c.metrics.recall ?? "n/a"} · mood: {c.metrics.mood ?? "n/a"}
                        </p>
                      )}
                      <Transcript lines={c.transcript} seniorName={senior.display_name} />
                    </div>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      </section>
      <ErrorBox error={calls.error} />
    </div>
  );
}
