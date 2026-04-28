"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { api, ApiError, type IngestionJob } from "@/lib/api";
import { Button } from "@/components/ui/button";

const TERMINAL = new Set(["validated", "rejected", "cancelled", "error", "ready_for_review"]);

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const data = await api.getJob(params.id);
        if (cancelled) return;
        setJob(data);
        setLoading(false);
        if (!TERMINAL.has(data.status)) {
          timer = setTimeout(load, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/sign-in");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load job.");
        setLoading(false);
      }
    }
    load();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [params.id, router]);

  if (loading) {
    return <Pad>Loading…</Pad>;
  }
  if (error) {
    return <Pad>{error}</Pad>;
  }
  if (!job) {
    return <Pad>Not found.</Pad>;
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-8 px-4 py-12 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard")}>
            ← Dashboard
          </Button>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight">
            {job.original_filename}
          </h1>
        </div>
        <StatusPill status={job.status} />
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <Card label="Source">{job.source_channel}</Card>
        <Card label="Size">{(job.file_size / 1024).toFixed(1)} KB</Card>
        <Card label="Engine">{job.extraction_engine || "—"}</Card>
        <Card label="Confidence">
          {job.extraction_confidence != null
            ? `${(job.extraction_confidence * 100).toFixed(0)}%`
            : "—"}
        </Card>
      </section>

      {job.error_message && (
        <section
          role="alert"
          className="rounded-md border border-error bg-error/5 px-4 py-3 text-xs text-error"
        >
          <div className="font-medium">Extraction error</div>
          <div className="mt-1">{job.error_message}</div>
        </section>
      )}

      {job.extracted_text && (
        <section>
          <h2 className="text-xl font-semibold">Extracted text</h2>
          <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-slate-100 bg-slate-50 p-4 font-mono text-2xs leading-relaxed text-slate-600">
            {job.extracted_text}
          </pre>
        </section>
      )}

      {job.state_transitions && job.state_transitions.length > 0 && (
        <section>
          <h2 className="text-xl font-semibold">State history</h2>
          <ul className="mt-3 divide-y divide-slate-100 border-y border-slate-100">
            {job.state_transitions.map((t, idx) => (
              <li key={idx} className="flex items-center justify-between py-2 text-2xs">
                <span className="font-medium uppercase tracking-wider text-slate-600">
                  {t.status.replace(/_/g, " ")}
                </span>
                <span className="text-slate-400">{new Date(t.at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {job.download_url && (
        <section>
          <a
            href={job.download_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-ink underline-offset-4 hover:underline"
          >
            Download original (link expires in 5 minutes)
          </a>
        </section>
      )}
    </main>
  );
}

function Pad({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl items-center justify-center px-4">
      <p className="text-slate-400">{children}</p>
    </main>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-base">{children}</div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "validated" || status === "ready_for_review"
      ? "bg-success/10 text-success"
      : status === "error" || status === "rejected"
        ? "bg-error/10 text-error"
        : "bg-slate-100 text-slate-600";
  return (
    <span className={["rounded-full px-3 py-1 text-2xs font-medium", tone].join(" ")}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
