"use client";

// Accept-invitation landing page (Slice 56). User arrives from
// /accept-invitation?token=<plaintext>. The flow:
//
//   1. Preview the invitation (anonymous endpoint) so we can show
//      "Join {Org} as {role}?" before asking the user to sign in.
//   2. If the user is signed in:
//        - email matches → "Accept" button → POST /invitations/accept/
//        - email differs → "Sign out + accept as <invited email>"
//   3. If the user is NOT signed in:
//        - existing user → link to /sign-in (we'll redirect back here).
//        - new user → link to /sign-up (will land + auto-accept).
//
// Token leaves the URL only after acceptance (the token is single-use
// once status flips to accepted) — no need to scrub.

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { api, ApiError, type Me } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Preview = {
  email: string;
  role: string;
  organization_legal_name: string;
  expires_at: string;
};

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={<Pad>Loading…</Pad>}>
      <AcceptInvitationInner />
    </Suspense>
  );
}

function AcceptInvitationInner() {
  const router = useRouter();
  const search = useSearchParams();
  const token = search.get("token") || "";

  const [preview, setPreview] = useState<Preview | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Missing invitation token.");
      setLoading(false);
      return;
    }
    Promise.all([
      api.previewInvitation(token).catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          throw new Error("This invitation isn't valid or has already been used.");
        }
        throw err;
      }),
      api.me().catch(() => null),
    ])
      .then(([p, m]) => {
        setPreview(p);
        setMe(m);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Couldn't load invitation.");
      })
      .finally(() => setLoading(false));
  }, [token]);

  async function accept() {
    setAccepting(true);
    setError(null);
    try {
      const result = await api.acceptInvitation(token);
      router.push(result.redirect_to);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Acceptance failed.");
    } finally {
      setAccepting(false);
    }
  }

  if (loading) return <Pad>Loading invitation…</Pad>;
  if (error)
    return (
      <Pad>
        <div className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error">
          {error}
        </div>
        <Link
          className="mt-4 text-2xs text-slate-500 underline"
          href="/sign-in"
        >
          Back to sign in
        </Link>
      </Pad>
    );
  if (!preview) return <Pad>Invitation not found.</Pad>;

  const emailMatches =
    me && me.email.toLowerCase() === preview.email.toLowerCase();

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-16 md:px-8">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight">
          You&apos;re invited
        </h1>
        <p className="mt-2 text-2xs text-slate-500">
          Join{" "}
          <span className="font-medium text-ink">
            {preview.organization_legal_name}
          </span>{" "}
          on ZeroKey as{" "}
          <span className="font-medium text-ink">{preview.role}</span>.
        </p>
        <p className="mt-1 text-[10px] text-slate-400">
          Invited address: {preview.email} · expires{" "}
          {new Date(preview.expires_at).toLocaleDateString()}
        </p>
      </div>

      {me ? (
        emailMatches ? (
          <Button onClick={accept} disabled={accepting}>
            {accepting ? "Joining…" : `Accept as ${me.email}`}
          </Button>
        ) : (
          <div className="rounded-md border border-amber-200 bg-amber-50/50 px-4 py-3 text-2xs text-amber-900">
            <p className="font-medium">Different email signed in</p>
            <p className="mt-1">
              You&apos;re signed in as{" "}
              <span className="font-mono">{me.email}</span> but this invite
              is for <span className="font-mono">{preview.email}</span>.
              Sign out + sign back in with the invited address.
            </p>
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              onClick={async () => {
                try {
                  await api.logout();
                } catch {}
                router.push(
                  `/sign-in?return_to=${encodeURIComponent(
                    `/accept-invitation?token=${encodeURIComponent(token)}`,
                  )}`,
                );
              }}
            >
              Sign out + continue
            </Button>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-2">
          <Link
            href={`/sign-in?return_to=${encodeURIComponent(
              `/accept-invitation?token=${encodeURIComponent(token)}`,
            )}`}
          >
            <Button className="w-full">Sign in to accept</Button>
          </Link>
          <p className="text-[10px] text-slate-400">
            Don&apos;t have an account yet?{" "}
            <Link
              className="text-ink underline"
              href={`/sign-up?invite=${encodeURIComponent(token)}`}
            >
              Sign up here
            </Link>{" "}
            — we&apos;ll add you to the org automatically.
          </p>
        </div>
      )}
    </main>
  );
}

function Pad({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-2 px-4 py-16 md:px-8">
      {children}
    </main>
  );
}
