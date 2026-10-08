import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus, Sparkles } from "lucide-react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { TopBar } from "../components/Layout";
import { Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Circles() {
  const { config, me } = useAuth();
  const q = useQuery({ queryKey: ["circles"], queryFn: api.circles });
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const seed = useMutation({
    mutationFn: api.demoSeed,
    onSuccess: (c) => {
      qc.invalidateQueries();
      toast("Demo circle created");
      nav(`/c/${c.id}`);
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (q.data && q.data.length === 1 && !sessionStorage.getItem("vc_stay")) {
    return <Navigate to={`/c/${q.data[0].id}`} replace />;
  }
  sessionStorage.setItem("vc_stay", "1");

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
        <PageHeader
          title={`Welcome${me?.full_name ? `, ${me.full_name}` : ""}`}
          subtitle="A circle is one older person plus the family members who look out for them."
          action={
            <Link to="/onboarding">
              <Button><Plus className="h-5 w-5" aria-hidden /> New circle</Button>
            </Link>
          }
        />
        {q.isLoading && <Spinner />}
        <ErrorBox error={q.error} />
        {q.data && q.data.length === 0 && (
          <Empty
            title="You don't have a circle yet"
            body="Set one up in about two minutes. You'll add your loved one's phone number and record your voice."
            action={
              <div className="flex flex-wrap justify-center gap-3">
                <Link to="/onboarding"><Button size="lg">Set up a circle</Button></Link>
                {config?.demo_mode && (
                  <Button size="lg" variant="secondary" loading={seed.isPending} onClick={() => seed.mutate()}>
                    <Sparkles className="h-5 w-5" aria-hidden /> Load demo data
                  </Button>
                )}
              </div>
            }
          />
        )}
        <ul className="space-y-4">
          {q.data?.map((c) => {
            const senior = c.members.find((m) => m.role === "senior");
            return (
              <li key={c.id}>
                <Link to={`/c/${c.id}`} className="block rounded-xl2 focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand">
                  <Card className="flex items-center justify-between gap-4 hover:border-brand">
                    <div>
                      <p className="font-display text-2xl font-bold">{c.name}</p>
                      <p className="mt-1 text-lg text-muted">
                        {senior ? `Protecting ${senior.display_name}` : "No senior added yet"} · {c.members.length} people
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      {!!c.stats?.open_alerts && <Badge tone="bad">{c.stats.open_alerts} alerts</Badge>}
                      <ChevronRight className="h-7 w-7 text-muted" aria-hidden />
                    </div>
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
        {q.data && q.data.length > 0 && config?.demo_mode && (
          <div className="mt-8">
            <Button variant="ghost" loading={seed.isPending} onClick={() => seed.mutate()}>
              <Sparkles className="h-5 w-5" aria-hidden /> Add another demo circle
            </Button>
          </div>
        )}
      </main>
    </div>
  );
}
