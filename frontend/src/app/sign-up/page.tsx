"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function SignUpPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [legalName, setLegalName] = useState("");
  const [tin, setTin] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.ensureCsrf().catch(() => {
      // Worst case: the user gets a 403 on submit; we surface it then.
    });
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.register({
        email,
        password,
        organization_legal_name: legalName,
        organization_tin: tin,
        contact_email: contactEmail || email,
      });
      router.push("/dashboard");
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
        Start your <em className="text-slate-600">free trial</em>
      </h1>
      <p className="text-base text-slate-600">
        14 days. 20 invoices. No credit card.
      </p>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field label="Your email" type="email" value={email} onChange={setEmail} required />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          required
          hint="At least 12 characters."
        />
        <Field
          label="Company legal name"
          value={legalName}
          onChange={setLegalName}
          required
        />
        <Field
          label="Tax Identification Number (TIN)"
          value={tin}
          onChange={setTin}
          required
          hint="From your LHDN registration."
        />
        <Field
          label="Operations contact email"
          type="email"
          value={contactEmail}
          onChange={setContactEmail}
          hint="Defaults to your email above if left blank."
        />

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error"
          >
            {error}
          </div>
        )}

        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating your account…" : "Create account"}
        </Button>
      </form>

      <p className="text-xs text-slate-400">
        Already have an account?{" "}
        <Link href="/sign-in" className="text-ink underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </main>
  );
}

function Field({
  label,
  type = "text",
  value,
  onChange,
  required,
  hint,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-2xs font-medium uppercase tracking-wider text-slate-400">
        {label}
        {required && <span className="ml-1 text-error">*</span>}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        className="rounded-md border border-slate-200 bg-white px-3 py-2 text-base text-ink focus:border-ink focus:outline-none"
      />
      {hint && <span className="text-2xs text-slate-400">{hint}</span>}
    </label>
  );
}
