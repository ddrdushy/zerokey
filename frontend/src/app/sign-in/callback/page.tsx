"use client";

// SSO callback (Slice 97).
//
// The IdP redirects here with ?code=<>&state=<> after the user
// authenticates. We POST those to /identity/sso/callback/ which
// validates them, JIT-provisions the User + Membership, and logs
// the user in via Django's session machinery. On success we
// redirect to the dashboard; on failure we surface the error and
// link back to /sign-in.

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";

// useSearchParams() must run beneath a Suspense boundary in Next 14, or
// the App Router's static prerender bails on this route. The IdP always
// supplies ?code & ?state, so this is purely a request-time concern.
export const dynamic = "force-dynamic";

export default function SsoCallbackPage() {
  return (
    <Suspense fallback={<CallbackFallback />}>
      <CallbackInner />
    </Suspense>
  );
}

function CallbackInner() {
  const router = useRouter();
  const search = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = search.get("code");
    const state = search.get("state");
    const idpError = search.get("error");
    if (idpError) {
      setError(`The identity provider rejected the sign-in: ${idpError}`);
      return;
    }
    if (!code || !state) {
      setError("Missing authorization code or state in the callback URL.");
      return;
    }
    api
      .ssoCallback(code, state)
      .then((me) => {
        router.push(me.is_staff ? "/admin" : "/dashboard");
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Sign-in failed.");
      });
  }, [search, router]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-16 md:px-8">
      <Link href="/" className="font-display text-xl font-bold tracking-tight">
        ZeroKey
      </Link>
      {error ? (
        <>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Sign-in didn&apos;t complete.
          </h1>
          <p
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-xs text-error"
          >
            {error}
          </p>
          <p className="text-xs text-slate-400">
            <Link href="/sign-in" className="text-ink underline-offset-4 hover:underline">
              Try again with email + password
            </Link>
          </p>
        </>
      ) : (
        <>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Finishing sign-in…
          </h1>
          <p className="text-sm text-slate-500">
            Verifying your identity with your provider.
          </p>
        </>
      )}
    </main>
  );
}

function CallbackFallback() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-16 md:px-8">
      <Link href="/" className="font-display text-xl font-bold tracking-tight">
        ZeroKey
      </Link>
      <h1 className="font-display text-2xl font-bold tracking-tight">
        Finishing sign-in…
      </h1>
    </main>
  );
}
