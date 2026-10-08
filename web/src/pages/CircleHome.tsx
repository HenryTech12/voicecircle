import { useQuery } from "@tanstack/react-query";
import { Bell, HeartHandshake, Mic, PhoneCall, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { useCircle } from "../components/Layout";
import { Badge, Button, Card, Empty, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { initials, timeAgo } from "../lib/format";

function Tile({ to, icon: Icon, label, value, note, tone }: { to: string; icon: typeof Mic; label: string; value: string; note: string; tone?: "bad" | "good" }) {
  return (
    <Link to={to} className="block rounded-xl2 focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand">
      <Card className="h-full hover:border-brand">
        <div className="flex items-center gap-2 text-lg font-bold text-muted">
          <Icon className="h-5 w-5" aria-hidden /> {label}
        </div>
        <p className={`mt-3 font-display text-4xl font-bold ${tone === "bad" ? "text-bad" : tone === "good" ? "text-good" : "text-ink"}`}>{value}</p>
        <p className="mt-1 text-base text-muted">{note}</p>
      </Card>
    </Link>
  );
}

export default function CircleHome() {
  const { circle, query, senior, contacts, circleId } = useCircle();
  const alerts = useQuery({ queryKey: ["alerts", circleId], queryFn: () => api.alerts(circleId), enabled: !!circleId });
  if (query.isLoading || !circle) return <Spinner />;
  const s = circle.stats!;
  const open = alerts.data?.filter((a) => !a.acknowledged_at) ?? [];

  return (
    <div>
      <PageHeader title={circle.name} subtitle={senior ? `Looking out for ${senior.display_name}, together.` : "Add the person you're protecting to get started."} />

      {!senior && (
        <Empty title="Add your loved one" body="VoiceCircle needs their name and phone number to call them." action={<Link to="voices"><Button>Add them now</Button></Link>} />
      )}

      {open.length > 0 && (
        <Card className="mb-6 border-2 border-bad/40 bg-bad-soft">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-lg font-bold text-bad">{open.length === 1 ? "1 thing needs your attention" : `${open.length} things need your attention`}</p>
              <p className="text-lg text-ink">{open[0].title}</p>
            </div>
            <Link to="alerts"><Button variant="danger">See alerts</Button></Link>
          </div>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile to="voices" icon={Mic} label="Trusted voices" value={`${s.voices_enrolled} of ${contacts.length}`} note="enrolled" />
        <Tile
          to="training"
          icon={PhoneCall}
          label="Last practice"
          value={s.last_practice_score === null ? "—" : `${s.last_practice_score}`}
          note={s.last_practice_at ? `score out of 100 · ${timeAgo(s.last_practice_at)}` : "No practice calls yet"}
          tone={s.last_practice_score === null ? undefined : s.last_practice_score >= 80 ? "good" : "bad"}
        />
        <Tile to="hugh" icon={HeartHandshake} label="Hugh's last call" value={s.last_companion_at ? timeAgo(s.last_companion_at) : "—"} note={senior?.companion_enabled ? `Daily at ${senior.companion_call_time}` : "Daily calls are off"} />
        <Tile to="alerts" icon={Bell} label="Open alerts" value={`${s.open_alerts}`} note={`${s.detections} recordings checked`} tone={s.open_alerts ? "bad" : "good"} />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="text-2xl font-bold">People in this circle</h2>
          <ul className="mt-4 divide-y divide-line">
            {circle.members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div className="flex items-center gap-4">
                  <span className={`flex h-12 w-12 items-center justify-center rounded-full text-lg font-bold ${m.role === "senior" ? "bg-brand text-white" : "bg-brand-soft text-brand-dark"}`} aria-hidden>
                    {initials(m.display_name)}
                  </span>
                  <div>
                    <p className="text-lg font-bold">{m.display_name}</p>
                    <p className="text-base text-muted">
                      {m.role === "senior" ? "Protected" : "Trusted contact"}
                      {m.relationship ? ` · ${m.relationship}` : ""}
                      {m.phone_e164 ? ` · ${m.phone_e164}` : ""}
                    </p>
                  </div>
                </div>
                {m.role === "trusted_contact" && (
                  <Badge tone={m.voice_status === "enrolled" ? "good" : m.voice_status === "failed" ? "bad" : "neutral"}>
                    {m.voice_status === "enrolled" ? "Voice enrolled" : m.voice_status === "processing" ? "Processing" : m.voice_status === "failed" ? "Enrollment failed" : "No voice yet"}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <h2 className="text-2xl font-bold">Quick actions</h2>
          <div className="mt-4 flex flex-col gap-3">
            <Link to="training"><Button className="w-full"><PhoneCall className="h-5 w-5" aria-hidden /> Run a practice call</Button></Link>
            <Link to="check"><Button variant="secondary" className="w-full"><ShieldCheck className="h-5 w-5" aria-hidden /> Check a recording</Button></Link>
            <Link to="hugh"><Button variant="secondary" className="w-full"><HeartHandshake className="h-5 w-5" aria-hidden /> See Hugh's calls</Button></Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
