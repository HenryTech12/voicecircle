import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setTokenProvider, tokenStore, type AuthConfig, type Me } from "./api";

const SB_URL = __SUPABASE_URL__ || undefined;
const SB_KEY = __SUPABASE_ANON_KEY__ || undefined;
const supabase: SupabaseClient | null = SB_URL && SB_KEY ? createClient(SB_URL, SB_KEY) : null;

interface AuthState {
  config: AuthConfig | null;
  me: Me | null;
  loading: boolean;
  error: string | null;
  loginLocal: (email: string, name?: string) => Promise<void>;
  sendMagicLink: (email: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<Me | null>;
}

const hasToken = async () => !!(await getToken());

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshMe = useCallback(async () => {
    try {
      const m = await api.me();
      setMe(m);
      return m;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;
    (async () => {
      try {
        const cfg = await api.authConfig();
        if (cancelled) return;
        setConfig(cfg);
        if (cfg.auth_mode === "supabase" && supabase) {
          setTokenProvider(async () => (await supabase.auth.getSession()).data.session?.access_token ?? null);
          const { data } = supabase.auth.onAuthStateChange((event) => {
            // INITIAL_SESSION is handled by the explicit refresh below; avoid duplicate /me calls.
            if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED") void refreshMe();
            if (event === "SIGNED_OUT") setMe(null);
          });
          unsubscribe = () => data.subscription.unsubscribe();
        }
        // Only call /me when we actually hold a token; otherwise it is a guaranteed 401.
        if (await hasToken()) await refreshMe();
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    const onUnauthorized = () => {
      // A 401 means the stored token is stale or invalid: drop it so we stop retrying with it.
      if (!supabase) tokenStore.clear();
      setMe(null);
    };
    window.addEventListener("vc:unauthorized", onUnauthorized);
    return () => {
      cancelled = true;
      unsubscribe?.();
      window.removeEventListener("vc:unauthorized", onUnauthorized);
    };
  }, [refreshMe]);

  const loginLocal = useCallback(
    async (email: string, name?: string) => {
      const res = await api.devLogin(email, name);
      tokenStore.set(res.access_token);
      await refreshMe();
    },
    [refreshMe],
  );

  const sendMagicLink = useCallback(async (email: string) => {
    if (!supabase) throw new Error("Supabase is not configured in this frontend (SUPABASE_URL / SUPABASE_ANON_KEY).");
    const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
    if (error) {
      const e = error as { status?: number; code?: string; message: string };
      if (e.status === 429 || e.code === "over_email_send_rate_limit" || /rate limit/i.test(e.message)) {
        throw new Error("Too many sign-in emails were requested. Please wait a few minutes and try again, and check your inbox and spam for a link we already sent.");
      }
      throw error;
    }
  }, []);

  const logout = useCallback(async () => {
    tokenStore.clear();
    if (supabase) await supabase.auth.signOut();
    setMe(null);
  }, []);

  const value = useMemo(
    () => ({ config, me, loading, error, loginLocal, sendMagicLink, logout, refreshMe }),
    [config, me, loading, error, loginLocal, sendMagicLink, logout, refreshMe],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
