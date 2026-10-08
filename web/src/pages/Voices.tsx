import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Trash2, UserPlus, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useCircle } from "../components/Layout";
import { Recorder, type Recording } from "../components/Recorder";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Spinner, useToast } from "../components/ui";
import { api, type Member, type Role } from "../lib/api";
import { useAuth } from "../lib/auth";
import { initials, toE164 } from "../lib/format";
import { COUNTRIES } from "./Onboarding";

/** Recording + consent + upload + status polling for one trusted contact. */
export function VoiceEnroll({ circleId, memberId, onDone }: { circleId: string; memberId: string; onDone?: () => void }) {
  const prompts = useQuery({ queryKey: ["prompts", circleId], queryFn: () => api.voicePrompts(circleId) });
  const [rec, setRec] = useState<Recording | null>(null);
  const [consent, setConsent] = useState(false);
  const [polling, setPolling] = useState(false);
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["voice", memberId],
    queryFn: () => api.voice(memberId),
    refetchInterval: polling ? 1500 : false,
  });
  const upload = useMutation({
    mutationFn: () => api.uploadVoice(memberId, rec!.blob, rec!.filename, prompts.data!.consent_version),
    onSuccess: () => {
      setPolling(true);
      qc.invalidateQueries({ queryKey: ["voice", memberId] });
    },
  });

  const st = status.data?.status;
  useEffect(() => {
    if (polling && (st === "enrolled" || st === "failed")) {
      setPolling(false);
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      if (st === "enrolled") onDone?.();
    }
  }, [st, polling, qc, circleId, onDone]);

  if (prompts.isLoading) return <Spinner />;
  if (polling || st === "processing")
    return (
      <div role="status" className="flex items-center gap-3 rounded-xl bg-brand-soft p-5 text-lg font-bold text-brand-dark">
        <Loader2 className="h-6 w-6 animate-spin" aria-hidden /> Creating the voice profile. This takes a few seconds…
      </div>
    );

  return (
    <div className="space-y-6">
      {st === "failed" && (
        <p role="alert" className="flex items-center gap-2 rounded-xl bg-bad-soft p-4 text-lg font-bold text-bad">
          <XCircle aria-hidden /> Last attempt failed: {status.data?.error || "please record again"}
        </p>
      )}
      <Recorder prompts={prompts.data?.prompts ?? []} onReady={setRec} />
      <label className="flex cursor-pointer items-start gap-3 rounded-xl border-2 border-line p-4">
        <input type="checkbox" className="mt-1 h-6 w-6 shrink-0 accent-brand" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span className="text-base leading-relaxed">{prompts.data?.consent_text}</span>
      </label>
      <ErrorBox error={upload.error} />
      <Button size="lg" disabled={!rec || !consent} loading={upload.isPending} onClick={() => upload.mutate()}>
        Save my voice
      </Button>
      {!consent && rec && <p className="text-base text-muted">Tick the consent box to continue.</p>}
    </div>
  );
}

function AddPerson({ circleId, role, onClose }: { circleId: string; role: Role; onClose: () => void }) {
  const [name, setName] = useState("");
  const [rel, setRel] = useState("");
  const [country, setCountry] = useState("+234");
  const [phone, setPhone] = useState("");
  const [isMe, setIsMe] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const m = useMutation({
    mutationFn: () =>
      api.addMember(circleId, {
        role,
        display_name: name.trim(),
        relationship: rel.trim() || null,
        phone_e164: toE164(country, phone) || null,
        timezone: COUNTRIES.find((c) => c.code === country)?.tz ?? "Africa/Lagos",
        companion_enabled: role === "senior",
        companion_call_time: role === "senior" ? "09:00" : null,
        link_to_me: isMe,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      toast(`${name} added`);
      onClose();
    },
  });
  return (
    <Card className="border-2 border-brand">
      <h2 className="text-2xl font-bold">{role === "senior" ? "Add the person you're protecting" : "Add a trusted contact"}</h2>
      <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="pname"><Input id="pname" required value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Relationship" htmlFor="prel"><Input id="prel" value={rel} onChange={(e) => setRel(e.target.value)} placeholder={role === "senior" ? "grandmother" : "granddaughter"} /></Field>
        </div>
        <Field label="Phone number" htmlFor="pphone">
          <div className="flex gap-2">
            <div className="w-48 shrink-0">
              <Select aria-label="Country code" value={country} onChange={(e) => setCountry(e.target.value)}>
                {COUNTRIES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
              </Select>
            </div>
            <Input id="pphone" type="tel" required={role === "senior"} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0803 123 4567" />
          </div>
        </Field>
        {role === "trusted_contact" && (
          <label className="flex items-center gap-3 text-lg">
            <input type="checkbox" className="h-6 w-6 accent-brand" checked={isMe} onChange={(e) => setIsMe(e.target.checked)} /> This is me
          </label>
        )}
        <ErrorBox error={m.error} />
        <div className="flex gap-3">
          <Button type="submit" loading={m.isPending}>Add</Button>
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function ContactRow({ m, circleId, mine }: { m: Member; circleId: string; mine: boolean }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const remove = useMutation({
    mutationFn: () => api.deleteVoice(m.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      qc.invalidateQueries({ queryKey: ["voice", m.id] });
      toast("Voice deleted. Its clone was removed from our voice provider too.");
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const enrolled = m.voice_status === "enrolled";
  return (
    <Card as="article">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-soft text-xl font-bold text-brand-dark" aria-hidden>{initials(m.display_name)}</span>
          <div>
            <p className="text-xl font-bold">{m.display_name}{mine ? " (you)" : ""}</p>
            <p className="text-base text-muted">{m.relationship || "Trusted contact"}{m.phone_e164 ? ` · ${m.phone_e164}` : ""}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {enrolled ? (
            <Badge tone="good"><CheckCircle2 className="h-4 w-4" aria-hidden /> Voice enrolled</Badge>
          ) : m.voice_status === "processing" ? (
            <Badge tone="brand">Processing</Badge>
          ) : m.voice_status === "failed" ? (
            <Badge tone="bad">Enrollment failed</Badge>
          ) : (
            <Badge>No voice yet</Badge>
          )}
          {enrolled ? (
            <Button variant="ghost" size="sm" loading={remove.isPending} onClick={() => confirm(`Delete ${m.display_name}'s voice profile? Practice calls and checks will stop working for this voice.`) && remove.mutate()}>
              <Trash2 className="h-5 w-5" aria-hidden /> Delete voice
            </Button>
          ) : (
            <Button size="sm" onClick={() => setOpen((o) => !o)}>{open ? "Close" : "Record voice"}</Button>
          )}
        </div>
      </div>
      {open && !enrolled && (
        <div className="mt-6 border-t border-line pt-6">
          {!mine && <p className="mb-4 rounded-xl bg-warn-soft p-4 text-base text-warn">Only record {m.display_name}'s voice with them present and agreeing. Better: send them this page so they can record it themselves.</p>}
          <VoiceEnroll circleId={circleId} memberId={m.id} onDone={() => setOpen(false)} />
        </div>
      )}
    </Card>
  );
}

export default function Voices() {
  const { circle, senior, contacts, circleId, query } = useCircle();
  const { me } = useAuth();
  const [adding, setAdding] = useState<Role | null>(null);
  if (query.isLoading || !circle) return <Spinner />;
  return (
    <div>
      <PageHeader
        title="Trusted voices"
        subtitle="Each family member records their voice once. We use it to tell real calls from fakes and to make safe practice calls."
        action={!adding && <Button onClick={() => setAdding("trusted_contact")}><UserPlus className="h-5 w-5" aria-hidden /> Add family member</Button>}
      />
      <div className="space-y-4">
        {!senior && !adding && (
          <Card className="border-2 border-warn/40 bg-warn-soft">
            <p className="text-lg font-bold text-warn">No protected person yet</p>
            <p className="text-lg">Add the older person this circle protects.</p>
            <Button className="mt-3" onClick={() => setAdding("senior")}>Add them</Button>
          </Card>
        )}
        {adding && <AddPerson circleId={circleId} role={adding} onClose={() => setAdding(null)} />}
        {contacts.map((m) => <ContactRow key={m.id} m={m} circleId={circleId} mine={m.user_id === me?.id} />)}
        {senior && (
          <p className="pt-2 text-base text-muted">
            {senior.display_name} doesn't record a voice. VoiceCircle calls them on {senior.phone_e164}.
          </p>
        )}
      </div>
    </div>
  );
}
