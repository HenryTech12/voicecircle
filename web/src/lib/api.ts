// Typed client for the VoiceCircle FastAPI backend (/api/v1).
// Types mirror app/schemas.py. Run `npm run gen:types` to generate OpenAPI types if you change the API.

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const PREFIX = `${API_BASE}/api/v1`;
const TOKEN_KEY = "vc_token";

export type Role = "senior" | "trusted_contact";
export type Difficulty = "easy" | "medium" | "hard";
export type VoiceStatus = "none" | "processing" | "enrolled" | "failed";

export interface User { id: string; email: string; full_name: string | null }
export interface Me extends User { circles: { id: string; name: string; role: string }[] }
export interface AuthConfig { auth_mode: "local" | "supabase"; mock_providers: boolean; demo_mode: boolean }

export interface Member {
  id: string; circle_id: string; user_id: string | null; role: Role; display_name: string;
  relationship: string | null; phone_e164: string | null; timezone: string;
  companion_call_time: string | null; companion_enabled: boolean; personal_facts: string[];
  voice_status: VoiceStatus; created_at: string;
}
export interface CircleStats {
  voices_enrolled: number; last_practice_score: number | null; last_practice_at: string | null;
  last_companion_at: string | null; open_alerts: number; detections: number;
}
export interface Circle { id: string; name: string; owner_id: string; created_at: string; members: Member[]; stats: CircleStats | null }

export interface VoiceInfo { id: string | null; status: VoiceStatus; error: string | null; consent_at: string | null; created_at: string | null }
export interface VoicePrompts { prompts: string[]; consent_text: string; consent_version: string }

export interface Scenario { key: string; title: string; description: string; difficulties: Difficulty[] }
export interface Line { speaker: "caller" | "senior" | "system" | "hugh"; text: string; t_ms: number }
export type Outcome = "hung_up_early" | "verified" | "refused" | "hesitated" | "complied";
export interface PracticeCall {
  id: string; circle_id: string; senior_member_id: string; voice_member_id: string; scenario: string;
  difficulty: Difficulty; status: "queued" | "dialing" | "in_progress" | "completed" | "failed" | "no_answer" | "cancelled";
  outcome: Outcome | null; score: number | null;
  feedback: { did_well?: string[]; practice_next?: string[]; hung_up_by_senior?: boolean; error?: string } | null;
  transcript: Line[]; turns: number; safety_stop: boolean; duration_seconds: number | null;
  scheduled_for: string | null; started_at: string | null; ended_at: string | null; created_at: string;
}

export type Verdict = "real" | "fake" | "not_them" | "unsure";
export interface Detection {
  id: string; circle_id: string; claimed_member_id: string; claimed_member_name: string | null;
  original_filename: string | null; status: "processing" | "done" | "failed"; verdict: Verdict | null;
  synthetic_score: number | null; speaker_match_score: number | null; explanation: string | null;
  error: string | null; created_at: string;
}

export interface CompanionMetrics {
  wpm: number | null; latency_ms: number | null; filler_rate: number | null; senior_words?: number;
  recall?: string; mood?: string; repetition?: boolean;
}
export interface CompanionCall {
  id: string; circle_id: string; senior_member_id: string; status: string; recall_question: string | null;
  transcript: Line[]; summary: string | null; metrics: CompanionMetrics | null; flags: string[];
  duration_seconds: number | null; started_at: string | null; ended_at: string | null; created_at: string;
}
export interface TrendPoint { date: string; wpm: number | null; latency_ms: number | null; filler_rate: number | null; recall: string | null; mood: string | null }
export interface Trends { member_id: string; days: number; points: TrendPoint[]; baseline: Record<string, number | null>; flags: string[] }

export interface Alert {
  id: string; circle_id: string; type: "scam_risk" | "wellbeing_change" | "detection_fake"; severity: "info" | "warning" | "urgent";
  title: string; message: string; source_id: string | null; acknowledged_at: string | null; created_at: string;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

let tokenProvider: () => Promise<string | null> = async () => tokenStore.get();
export function setTokenProvider(fn: () => Promise<string | null>) {
  tokenProvider = fn;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = await tokenProvider();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(`${PREFIX}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "network", "Can't reach VoiceCircle right now. Check your connection and that the server is running.");
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string } } | null)?.error;
    if (res.status === 401) window.dispatchEvent(new Event("vc:unauthorized"));
    throw new ApiError(res.status, err?.code || "error", err?.message || `Something went wrong (${res.status}).`);
  }
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b);
const patch = <T,>(p: string, b?: unknown) => request<T>("PATCH", p, b);
const del = <T,>(p: string) => request<T>("DELETE", p);

export const api = {
  health: () => get<{ status: string; mock_providers: boolean }>("/health"),
  authConfig: () => get<AuthConfig>("/auth/config"),
  devLogin: (email: string, full_name?: string) =>
    post<{ access_token: string; user: User }>("/auth/dev-login", { email, full_name }),
  me: () => get<Me>("/me"),

  circles: () => get<Circle[]>("/circles"),
  circle: (id: string) => get<Circle>(`/circles/${id}`),
  createCircle: (b: { name: string; my_display_name?: string; my_relationship?: string; my_phone_e164?: string }) =>
    post<Circle>("/circles", b),
  renameCircle: (id: string, name: string) => patch<Circle>(`/circles/${id}`, { name }),
  deleteCircle: (id: string) => del<{ ok: boolean }>(`/circles/${id}`),

  addMember: (circleId: string, b: Partial<Member> & { role: Role; display_name: string; link_to_me?: boolean }) =>
    post<Member>(`/circles/${circleId}/members`, b),
  updateMember: (id: string, b: Partial<Member>) => patch<Member>(`/members/${id}`, b),
  deleteMember: (id: string) => del<{ ok: boolean }>(`/members/${id}`),

  voicePrompts: (circleId?: string) => get<VoicePrompts>(`/voice/prompts${circleId ? `?circle_id=${circleId}` : ""}`),
  voice: (memberId: string) => get<VoiceInfo>(`/members/${memberId}/voice`),
  uploadVoice: (memberId: string, file: Blob, filename: string, consentVersion: string) => {
    const fd = new FormData();
    fd.append("file", file, filename);
    fd.append("consent", "true");
    fd.append("consent_version", consentVersion);
    return post<VoiceInfo>(`/members/${memberId}/voice`, fd);
  },
  deleteVoice: (memberId: string) => del<{ ok: boolean }>(`/members/${memberId}/voice`),

  scenarios: () => get<Scenario[]>("/practice/scenarios"),
  practiceCalls: (circleId: string) => get<PracticeCall[]>(`/circles/${circleId}/practice-calls`),
  practiceCall: (id: string) => get<PracticeCall>(`/practice-calls/${id}`),
  startPractice: (circleId: string, b: { senior_member_id: string; voice_member_id: string; scenario: string; difficulty: Difficulty; scheduled_for?: string }) =>
    post<PracticeCall>(`/circles/${circleId}/practice-calls`, b),
  cancelPractice: (id: string) => post<PracticeCall>(`/practice-calls/${id}/cancel`),

  detections: (circleId: string) => get<Detection[]>(`/circles/${circleId}/detections`),
  detection: (id: string) => get<Detection>(`/detections/${id}`),
  checkRecording: (circleId: string, file: File, claimedMemberId: string) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("claimed_member_id", claimedMemberId);
    return post<Detection>(`/circles/${circleId}/detections`, fd);
  },

  callHugh: (memberId: string) => post<CompanionCall>(`/members/${memberId}/companion-calls`),
  companionCalls: (memberId: string) => get<CompanionCall[]>(`/members/${memberId}/companion-calls`),
  companionCall: (id: string) => get<CompanionCall>(`/companion-calls/${id}`),
  trends: (memberId: string, days = 14) => get<Trends>(`/members/${memberId}/companion-trends?days=${days}`),

  alerts: (circleId: string) => get<Alert[]>(`/circles/${circleId}/alerts`),
  ackAlert: (id: string) => post<Alert>(`/alerts/${id}/ack`),

  simSay: (callId: string, text: string) => post<{ ok: boolean }>(`/dev/calls/${callId}/say`, { text }),
  simHangup: (callId: string) => post<{ ok: boolean }>(`/dev/calls/${callId}/hangup`),
  simSms: () => get<{ messages: { to: string; text: string }[] }>("/dev/sms"),

  demoSeed: () => post<Circle>("/demo/seed"),
  demoReset: () => post<{ ok: boolean; detail: string }>("/demo/reset"),
};
