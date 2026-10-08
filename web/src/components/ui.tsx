import { Loader2 } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-dark disabled:bg-brand/50",
  secondary: "bg-surface text-ink border-2 border-line hover:border-brand disabled:opacity-50",
  ghost: "text-brand hover:bg-brand-soft disabled:opacity-50",
  danger: "bg-bad text-white hover:bg-bad/90 disabled:opacity-50",
};

export function Button({
  variant = "primary", loading, size = "md", className = "", children, ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; size?: "md" | "lg" | "sm" }) {
  const sizes = { sm: "min-h-[40px] px-3 text-base", md: "min-h-[48px] px-5 text-lg", lg: "min-h-[60px] px-7 text-xl" };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-bold transition-colors focus-visible:outline focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed ${sizes[size]} ${variants[variant]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="h-5 w-5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ children, className = "", as: As = "section" }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" }) {
  return <As className={`rounded-xl2 border border-line bg-surface p-5 sm:p-6 ${className}`}>{children}</As>;
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl font-bold leading-tight sm:text-4xl">{title}</h1>
        {subtitle && <p className="mt-2 max-w-2xl text-lg text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

const tones = {
  good: "bg-good-soft text-good",
  bad: "bg-bad-soft text-bad",
  warn: "bg-warn-soft text-warn",
  neutral: "bg-bg text-muted border border-line",
  brand: "bg-brand-soft text-brand-dark",
};
export function Badge({ tone = "neutral", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-base font-bold ${tones[tone]}`}>{children}</span>;
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: string; error?: string | null; children: ReactNode; htmlFor: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-lg font-bold">{label}</label>
      {hint && <p id={`${htmlFor}-hint`} className="text-base text-muted">{hint}</p>}
      {children}
      {error && <p role="alert" className="text-base font-bold text-bad">{error}</p>}
    </div>
  );
}

const inputCls = "w-full min-h-[52px] rounded-xl border-2 border-line bg-white px-4 text-lg text-ink placeholder:text-muted/70 focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/20";
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={inputCls} {...props} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={inputCls} {...props} />;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-10 text-lg text-muted">
      <Loader2 className="h-6 w-6 animate-spin text-brand" aria-hidden /> {label}…
    </div>
  );
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="rounded-xl2 border-2 border-dashed border-line px-6 py-10 text-center">
      <p className="text-xl font-bold">{title}</p>
      {body && <p className="mx-auto mt-2 max-w-md text-lg text-muted">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-xl border-2 border-bad/30 bg-bad-soft px-4 py-3 text-lg text-bad">
      {(error as Error).message || "Something went wrong."}
    </div>
  );
}

// ---------------------------------------------------------------- toasts

interface Toast { id: number; text: string; tone: "good" | "bad" }
const ToastCtx = createContext<(text: string, tone?: "good" | "bad") => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "good" | "bad" = "good") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} className={`max-w-lg rounded-xl px-5 py-3 text-lg font-bold shadow-lg ${t.tone === "good" ? "bg-ink text-white" : "bg-bad text-white"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
