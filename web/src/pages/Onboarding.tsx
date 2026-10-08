import { useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/Layout";
import { Button, Card, ErrorBox, Field, Input, Select } from "../components/ui";
import { api, type Circle } from "../lib/api";
import { useAuth } from "../lib/auth";
import { toE164 } from "../lib/format";
import { VoiceEnroll } from "./Voices";

export const COUNTRIES = [
  { code: "+234", label: "Nigeria (+234)", tz: "Africa/Lagos" },
  { code: "+1", label: "USA / Canada (+1)", tz: "America/New_York" },
  { code: "+44", label: "United Kingdom (+44)", tz: "Europe/London" },
  { code: "+233", label: "Ghana (+233)", tz: "Africa/Accra" },
  { code: "+254", label: "Kenya (+254)", tz: "Africa/Nairobi" },
  { code: "+27", label: "South Africa (+27)", tz: "Africa/Johannesburg" },
  { code: "+91", label: "India (+91)", tz: "Asia/Kolkata" },
];

const STEPS = ["Your circle", "Your loved one", "Your voice"];

export default function Onboarding() {
  const { me, refreshMe } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [circle, setCircle] = useState<Circle | null>(null);

  const [circleName, setCircleName] = useState("");
  const [myName, setMyName] = useState(me?.full_name ?? "");
  const [myRel, setMyRel] = useState("");
  const [myCountry, setMyCountry] = useState("+234");
  const [myPhone, setMyPhone] = useState("");

  const [sName, setSName] = useState("");
  const [sRel, setSRel] = useState("");
  const [sCountry, setSCountry] = useState("+234");
  const [sPhone, setSPhone] = useState("");
  const [sTime, setSTime] = useState("09:00");
  const [sCompanion, setSCompanion] = useState(true);

  async function createCircle(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const c = await api.createCircle({
        name: circleName.trim(),
        my_display_name: myName.trim() || undefined,
        my_relationship: myRel.trim() || undefined,
        my_phone_e164: toE164(myCountry, myPhone) || undefined,
      });
      setCircle(c);
      setStep(1);
      await refreshMe();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function addSenior(e: React.FormEvent) {
    e.preventDefault();
    if (!circle) return;
    setBusy(true);
    setError(null);
    try {
      await api.addMember(circle.id, {
        role: "senior",
        display_name: sName.trim(),
        relationship: sRel.trim() || null,
        phone_e164: toE164(sCountry, sPhone),
        timezone: COUNTRIES.find((c) => c.code === sCountry)?.tz ?? "Africa/Lagos",
        companion_call_time: sTime,
        companion_enabled: sCompanion,
      });
      setCircle(await api.circle(circle.id));
      setStep(2);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const myMember = circle?.members.find((m) => m.user_id === me?.id);

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        <ol className="mb-8 flex items-center gap-2" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s} className="flex flex-1 items-center gap-2">
              <span
                aria-current={i === step ? "step" : undefined}
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-lg font-bold ${
                  i < step ? "bg-good text-white" : i === step ? "bg-brand text-white" : "bg-line text-muted"
                }`}
              >
                {i < step ? <Check className="h-5 w-5" aria-label="done" /> : i + 1}
              </span>
              <span className={`hidden text-base font-bold sm:inline ${i === step ? "text-ink" : "text-muted"}`}>{s}</span>
            </li>
          ))}
        </ol>

        {step === 0 && (
          <Card>
            <h1 className="font-display text-3xl font-bold">Create your circle</h1>
            <p className="mt-2 text-lg text-muted">A circle is one older person and the family who look out for them.</p>
            <form className="mt-6 space-y-5" onSubmit={createCircle}>
              <Field label="Circle name" hint="For example: Grandma Ada's Circle" htmlFor="cname">
                <Input id="cname" required value={circleName} onChange={(e) => setCircleName(e.target.value)} />
              </Field>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Your name" htmlFor="myname">
                  <Input id="myname" required value={myName} onChange={(e) => setMyName(e.target.value)} placeholder="Alex" />
                </Field>
                <Field label="You are their…" htmlFor="myrel">
                  <Input id="myrel" value={myRel} onChange={(e) => setMyRel(e.target.value)} placeholder="grandson" />
                </Field>
              </div>
              <Field label="Your phone number" hint="We text you if something needs attention." htmlFor="myphone">
                <div className="flex gap-2">
                  <div className="w-48 shrink-0">
                    <Select aria-label="Your country code" value={myCountry} onChange={(e) => setMyCountry(e.target.value)}>
                      {COUNTRIES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                    </Select>
                  </div>
                  <Input id="myphone" type="tel" inputMode="tel" value={myPhone} onChange={(e) => setMyPhone(e.target.value)} placeholder="0803 123 4567" />
                </div>
              </Field>
              <ErrorBox error={error} />
              <Button type="submit" size="lg" loading={busy}>Continue</Button>
            </form>
          </Card>
        )}

        {step === 1 && (
          <Card>
            <h1 className="font-display text-3xl font-bold">Who are you protecting?</h1>
            <p className="mt-2 text-lg text-muted">VoiceCircle calls this person on their normal phone. They don't need an app.</p>
            <form className="mt-6 space-y-5" onSubmit={addSenior}>
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Their name" hint="What Hugh will call them" htmlFor="sname">
                  <Input id="sname" required value={sName} onChange={(e) => setSName(e.target.value)} placeholder="Grandma Ada" />
                </Field>
                <Field label="They are your…" hint=" " htmlFor="srel">
                  <Input id="srel" value={sRel} onChange={(e) => setSRel(e.target.value)} placeholder="grandmother" />
                </Field>
              </div>
              <Field label="Their phone number" htmlFor="sphone">
                <div className="flex gap-2">
                  <div className="w-48 shrink-0">
                    <Select aria-label="Their country code" value={sCountry} onChange={(e) => setSCountry(e.target.value)}>
                      {COUNTRIES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                    </Select>
                  </div>
                  <Input id="sphone" type="tel" inputMode="tel" required value={sPhone} onChange={(e) => setSPhone(e.target.value)} placeholder="0803 123 4567" />
                </div>
              </Field>
              <label className="flex min-h-[52px] cursor-pointer items-start gap-3 rounded-xl border-2 border-line p-4">
                <input type="checkbox" className="mt-1 h-6 w-6 accent-brand" checked={sCompanion} onChange={(e) => setSCompanion(e.target.checked)} />
                <span>
                  <span className="block text-lg font-bold">Daily check-in calls from Hugh</span>
                  <span className="text-base text-muted">A friendly 3-minute chat each day. We'll let you know if anything seems different.</span>
                </span>
              </label>
              {sCompanion && (
                <Field label="Best time for Hugh to call" htmlFor="stime">
                  <Input id="stime" type="time" value={sTime} onChange={(e) => setSTime(e.target.value)} />
                </Field>
              )}
              <ErrorBox error={error} />
              <Button type="submit" size="lg" loading={busy}>Continue</Button>
            </form>
          </Card>
        )}

        {step === 2 && circle && myMember && (
          <Card>
            <h1 className="font-display text-3xl font-bold">Record your voice</h1>
            <p className="mt-2 text-lg text-muted">
              About 30–60 seconds. We use it to check if a caller is really you, and to make safe practice calls.
            </p>
            <div className="mt-6">
              <VoiceEnroll
                circleId={circle.id}
                memberId={myMember.id}
                onDone={() => {
                  qc.invalidateQueries();
                  nav(`/c/${circle.id}`);
                }}
              />
            </div>
            <Button variant="ghost" className="mt-4" onClick={() => nav(`/c/${circle.id}`)}>Skip for now</Button>
          </Card>
        )}
      </main>
    </div>
  );
}
