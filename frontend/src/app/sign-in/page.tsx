"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Slice 89 — when the credentials check passes but 2FA is on,
  // we flip into a "challenge" mode where the password fields are
  // hidden and a 6-digit (or recovery) code input takes over.
  const [needs2fa, setNeeds2fa] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.ensureCsrf().catch(() => {});
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (needs2fa) {
        const me = await api.loginTwoFactor(code.trim());
        router.push(me.is_staff ? "/admin" : "/dashboard");
        return;
      }
      const result = await api.login(email, password);
      if ("needs_2fa" in result && result.needs_2fa) {
        setNeeds2fa(true);
        setSubmitting(false);
        return;
      }
      const me = result as { is_staff: boolean };
      router.push(me.is_staff ? "/admin" : "/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-16 md:px-8">
      <Link href="/" className="font-display text-xl font-bold tracking-tight">
        ZeroKey
      </Link>
      <h1 className="font-display text-3xl font-bold tracking-tight">
        {needs2fa ? "Two-factor code" : "Welcome back."}
      </h1>
      {needs2fa && (
        <p className="text-2xs text-slate-500">
          Open your authenticator app and enter the 6-digit code, or use one of your recovery codes.
        </p>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {!needs2fa && (
          <>
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                Email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-base text-ink focus:border-ink focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
                Password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-base text-ink focus:border-ink focus:outline-none"
              />
            </label>
          </>
        )}

        {needs2fa && (
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
              Authenticator code
            </span>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              autoFocus
              autoComplete="one-time-code"
              inputMode="numeric"
              placeholder="123 456"
              className="rounded-md border border-slate-200 bg-white px-3 py-2 text-base text-ink focus:border-ink focus:outline-none"
            />
          </label>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error"
          >
            {error}
          </div>
        )}

        <Button type="submit" disabled={submitting}>
          {submitting ? (needs2fa ? "Verifying…" : "Signing in…") : needs2fa ? "Verify" : "Sign in"}
        </Button>
      </form>

      <p className="text-xs text-slate-400">
        Need an account?{" "}
        <Link href="/sign-up" className="text-ink underline-offset-4 hover:underline">
          Start a free trial
        </Link>
      </p>
    </main>
  );
}
