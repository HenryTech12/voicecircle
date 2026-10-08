import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bell, HeartHandshake, Home, LogOut, Mic, PhoneCall, ShieldCheck } from "lucide-react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export function Logo() {
  return (
    <span className="flex items-center gap-2 font-display text-2xl font-bold text-brand-dark">
      <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden fill="none">
        <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="3" />
        <path d="M10 17c2-4 4-4 6 0s4 4 6 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      VoiceCircle
    </span>
  );
}

export function useCircle() {
  const { circleId = "" } = useParams();
  const q = useQuery({ queryKey: ["circle", circleId], queryFn: () => api.circle(circleId), enabled: !!circleId });
  const members = q.data?.members ?? [];
  return {
    circleId,
    circle: q.data,
    query: q,
    senior: members.find((m) => m.role === "senior"),
    contacts: members.filter((m) => m.role === "trusted_contact"),
  };
}

const NAV = [
  { to: "", label: "Home", icon: Home, end: true },
  { to: "voices", label: "Voices", icon: Mic },
  { to: "training", label: "Practice", icon: PhoneCall },
  { to: "check", label: "Check a call", icon: ShieldCheck },
  { to: "hugh", label: "Hugh", icon: HeartHandshake },
  { to: "alerts", label: "Alerts", icon: Bell },
];

export function TopBar({ children }: { children?: React.ReactNode }) {
  const { me, logout, config } = useAuth();
  const nav = useNavigate();
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <NavLink to="/" aria-label="VoiceCircle home"><Logo /></NavLink>
        <div className="flex items-center gap-3">
          {config?.mock_providers && (
            <span className="hidden rounded-full bg-warn-soft px-3 py-1 text-sm font-bold text-warn sm:inline" title="Calls are simulated. Set MOCK_PROVIDERS=false on the server for real calls.">
              Demo mode: simulated calls
            </span>
          )}
          {children}
          {me && (
            <button
              onClick={async () => { await logout(); nav("/login"); }}
              className="flex min-h-[44px] items-center gap-2 rounded-xl px-3 text-base font-bold text-muted hover:bg-bg focus-visible:outline focus-visible:outline-4 focus-visible:outline-brand"
            >
              <LogOut className="h-5 w-5" aria-hidden /> <span className="hidden sm:inline">Sign out</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

export function CircleLayout() {
  const { circle, query } = useCircle();
  const openAlerts = circle?.stats?.open_alerts ?? 0;
  return (
    <div className="min-h-screen pb-24 sm:pb-10">
      <TopBar>
        {circle && (
          <NavLink to="/" className="hidden max-w-[240px] truncate rounded-xl border-2 border-line px-3 py-2 text-base font-bold md:block" title="Switch circle">
            {circle.name}
          </NavLink>
        )}
      </TopBar>
      <nav aria-label="Circle sections" className="hidden border-b border-line bg-surface sm:block">
        <ul className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 sm:px-6">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `flex min-h-[52px] items-center gap-2 border-b-4 px-4 text-lg font-bold ${isActive ? "border-brand text-brand-dark" : "border-transparent text-muted hover:text-ink"}`
                }
              >
                <n.icon className="h-5 w-5" aria-hidden /> {n.label}
                {n.to === "alerts" && openAlerts > 0 && (
                  <span className="rounded-full bg-bad px-2 text-sm text-white" aria-label={`${openAlerts} open alerts`}>{openAlerts}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {query.isError ? (
          <div role="alert" className="flex items-center gap-3 rounded-xl bg-bad-soft p-5 text-lg text-bad">
            <AlertTriangle aria-hidden /> {(query.error as Error).message}
          </div>
        ) : (
          <Outlet />
        )}
      </main>
      {/* mobile bottom nav */}
      <nav aria-label="Circle sections" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface sm:hidden">
        <ul className="grid grid-cols-6">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                className={({ isActive }) => `relative flex min-h-[64px] flex-col items-center justify-center gap-1 text-xs font-bold ${isActive ? "text-brand-dark" : "text-muted"}`}
              >
                <n.icon className="h-6 w-6" aria-hidden />
                {n.label.split(" ")[0]}
                {n.to === "alerts" && openAlerts > 0 && <span className="absolute right-3 top-2 h-3 w-3 rounded-full bg-bad" aria-label={`${openAlerts} open alerts`} />}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
