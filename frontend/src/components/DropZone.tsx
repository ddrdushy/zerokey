"use client";

import { useCallback, useRef, useState } from "react";

import { api, ApiError, type IngestionJob } from "@/lib/api";

const ACCEPTED = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/csv",
  "application/zip",
].join(",");

export function DropZone({
  onUploaded,
}: {
  onUploaded: (job: IngestionJob) => void;
}) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      setError(null);
      setBusy(true);
      try {
        for (const file of Array.from(files)) {
          const job = await api.uploadFile(file);
          onUploaded(job);
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Upload failed.");
      } finally {
        setBusy(false);
      }
    },
    [onUploaded],
  );

  return (
    <div className="rounded-xl border border-slate-100 bg-white p-8">
      <h2 className="text-xl font-semibold">Drop your invoice</h2>
      <p className="mt-2 max-w-2xl text-base text-slate-600">
        PDF, image, Excel, CSV, or ZIP. Up to 25 MB per file.
      </p>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setActive(true);
        }}
        onDragLeave={() => setActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setActive(false);
          if (e.dataTransfer.files.length > 0) upload(e.dataTransfer.files);
        }}
        className={[
          "mt-6 flex h-40 w-full items-center justify-center rounded-lg border-2 border-dashed transition-all duration-ack ease-zk",
          active
            ? "scale-[1.01] border-ink bg-signal/40"
            : "border-slate-200 bg-slate-50 hover:bg-slate-100",
        ].join(" ")}
      >
        {busy ? (
          <span className="text-slate-600">Uploading…</span>
        ) : (
          <span className="text-slate-400">
            Drag a file here, or <span className="text-ink underline">click to browse</span>
          </span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) upload(e.target.files);
            e.target.value = "";
          }}
        />
      </button>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-error bg-error/5 px-4 py-2 text-xs text-error"
        >
          {error}
        </div>
      )}
    </div>
  );
}
