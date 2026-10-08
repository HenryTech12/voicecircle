import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Logo } from "../components/Layout";
import { Button, Card, ErrorBox, Field, Input } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { me, config, loginLocal, sendMagicLink, error: bootError } = useAuth();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);

  if (me) return <Navigate to="/" replace />;
  const local = config?.auth_mode !== "supabase";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (local) await loginLocal(email, name || undefined);
      else {
        await sendMagicLink(email);
        setSent(true);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <section className="flex flex-1 flex-col justify-between bg-brand-dark p-8 text-white sm:p-12">
        <span className="text-white [&_*]:text-white"><Logo /></span>
        <div className="my-12 max-w-xl">
          <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl">
            The voices you trust, protecting the people you love.
          </h1>
          <p className="mt-5 text-xl text-white/85">
            VoiceCircle helps older adults spot AI voice scams. Family records a voice once. Then we run safe practice calls,
            check suspicious recordings, and Hugh calls every day for a friendly chat.
          </p>
        </div>
        <ul className="grid gap-3 text-lg text-white/90 sm:grid-cols-2">
          <li>• Works on any phone, no app to install</li>
          <li>• Practice scam calls in a family voice</li>
          <li>• Real-or-fake check for strange calls</li>
          <li>• Daily check-ins with gentle alerts</li>
        </ul>
      </section>
      <section className="flex flex-1 items-center justify-center p-6 sm:p-12">
        <Card className="w-full max-w-md">
          <h2 className="font-display text-3xl font-bold">Sign in</h2>
          <p className="mt-2 text-lg text-muted">
            {local ? "Enter your email to continue. No password needed in this version." : "We'll email you a sign-in link."}
          </p>
          {sent ? (
            <p role="status" className="mt-6 rounded-xl bg-good-soft p-4 text-lg font-bold text-good">
              Check your email for the sign-in link.
            </p>
          ) : (
            <form className="mt-6 space-y-5" onSubmit={submit}>
              <Field label="Email" htmlFor="email">
                <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </Field>
              {local && (
                <Field label="Your first name" hint="Shown to your family in the circle." htmlFor="name">
                  <Input id="name" autoComplete="given-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex" />
                </Field>
              )}
              <ErrorBox error={error || (bootError ? new Error(`Can't reach the server: ${bootError}`) : null)} />
              <Button type="submit" size="lg" className="w-full" loading={busy}>
                {local ? "Continue" : "Email me a link"}
              </Button>
            </form>
          )}
        </Card>
      </section>
    </div>
  );
}
