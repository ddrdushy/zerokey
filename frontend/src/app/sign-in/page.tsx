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
      const me = await api.login(email, password);
      // Platform staff are operator-only — they don't have or need an
      // active org context, so we route them straight to /admin and
      // skip the customer dashboard entirely. Customers continue to
      // land on /dashboard.
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
      <h1 className="font-display text-3xl font-bold tracking-tight">Welcome back.</h1>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
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

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error"
          >
            {error}
          </div>
        )}

        <Button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
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
