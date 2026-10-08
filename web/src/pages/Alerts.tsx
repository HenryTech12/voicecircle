import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, Check, Info } from "lucide-react";
import { Link } from "react-router-dom";
import { useCircle } from "../components/Layout";
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, useToast } from "../components/ui";
import { api, type Alert } from "../lib/api";
import { dateTime } from "../lib/format";

const SEV = {
  urgent: { icon: AlertOctagon, label: "Urgent", tone: "bad" as const, card: "border-bad/50" },
  warning: { icon: AlertTriangle, label: "Heads up", tone: "warn" as const, card: "border-warn/50" },
  info: { icon: Info, label: "For your info", tone: "brand" as const, card: "border-line" },
};
const LINK = { scam_risk: "training", wellbeing_change: "hugh", detection_fake: "check" } as const;

export default function Alerts() {
  const { circleId } = useCircle();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["alerts", circleId], queryFn: () => api.alerts(circleId), enabled: !!circleId, refetchInterval: 15000 });
  const ack = useMutation({
    mutationFn: (id: string) => api.ackAlert(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts", circleId] });
      qc.invalidateQueries({ queryKey: ["circle", circleId] });
      toast("Marked as handled");
    },
  });
  if (q.isLoading) return <Spinner />;
  const open = q.data?.filter((a) => !a.acknowledged_at) ?? [];
  const done = q.data?.filter((a) => a.acknowledged_at) ?? [];

  const Row = ({ a }: { a: Alert }) => {
    const s = SEV[a.severity];
    return (
      <Card as="article" className={`border-2 ${a.acknowledged_at ? "border-line opacity-80" : s.card}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex gap-4">
            <s.icon className={`mt-1 h-7 w-7 shrink-0 ${s.tone === "bad" ? "text-bad" : s.tone === "warn" ? "text-warn" : "text-brand"}`} aria-hidden />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={s.tone}>{s.label}</Badge>
                <span className="text-base text-muted">{dateTime(a.created_at)}</span>
              </div>
              <h2 className="mt-2 text-xl font-bold">{a.title}</h2>
              <p className="mt-1 text-lg">{a.message}</p>
              <Link to={`../${LINK[a.type]}`} relative="path" className="mt-2 inline-block text-lg font-bold text-brand underline underline-offset-4">See details</Link>
            </div>
          </div>
          {a.acknowledged_at ? (
            <Badge tone="good"><Check className="h-4 w-4" aria-hidden /> Handled</Badge>
          ) : (
            <Button variant="secondary" loading={ack.isPending && ack.variables === a.id} onClick={() => ack.mutate(a.id)}>
              <Check className="h-5 w-5" aria-hidden /> Mark as handled
            </Button>
          )}
        </div>
      </Card>
    );
  };

  return (
    <div>
      <PageHeader title="Alerts" subtitle="When something needs a family member's attention, it shows up here and we text the trusted contacts." />
      <ErrorBox error={q.error} />
      {open.length === 0 ? (
        <Empty title="All clear" body="Nothing needs your attention right now." />
      ) : (
        <div className="space-y-4">{open.map((a) => <Row key={a.id} a={a} />)}</div>
      )}
      {done.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-4 text-2xl font-bold">Handled</h2>
          <div className="space-y-4">{done.map((a) => <Row key={a.id} a={a} />)}</div>
        </section>
      )}
    </div>
  );
}
