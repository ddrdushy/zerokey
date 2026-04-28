"use client";

// Source-document pane on the side-by-side review screen. Native rendering
// only — no react-pdf. The browser knows how to display PDFs via <iframe>
// and images via <img>, and the presigned URL is short-lived (5 minutes)
// so we don't worry about caching beyond what the browser does. This keeps
// the bundle out of the ~500KB pdfjs hit until we actually need page-level
// rendering controls (zoom, page nav, annotation overlays).

import { FileText, FileWarning, ImageIcon } from "lucide-react";

type Props = {
  filename: string;
  mimeType: string;
  downloadUrl: string | null;
};

export function DocumentPreview({ filename, mimeType, downloadUrl }: Props) {
  const kind = classify(mimeType);

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-slate-100 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2 text-2xs uppercase tracking-wider text-slate-500">
          {kind === "pdf" && <FileText className="h-3.5 w-3.5" />}
          {kind === "image" && <ImageIcon className="h-3.5 w-3.5" />}
          {kind === "other" && <FileWarning className="h-3.5 w-3.5" />}
          <span className="truncate font-medium">{filename}</span>
        </div>
        {downloadUrl && (
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-2xs font-medium text-ink underline-offset-4 hover:underline"
          >
            Open
          </a>
        )}
      </header>
      <div className="relative flex-1 bg-slate-50">
        {downloadUrl == null ? (
          <Empty message="The download link expired. Refresh to get a new one." />
        ) : kind === "pdf" ? (
          <iframe
            // sandbox without `allow-scripts` keeps the embedded PDF from
            // running anything weird; LHDN-shape PDFs are static documents,
            // there's no good reason to grant scripting to the embed.
            sandbox="allow-same-origin"
            src={`${downloadUrl}#toolbar=0&navpanes=0`}
            title={`Source: ${filename}`}
            className="h-full w-full border-0 bg-white"
          />
        ) : kind === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={downloadUrl}
            alt={`Source document: ${filename}`}
            className="h-full w-full object-contain bg-white"
          />
        ) : (
          <Empty message={`Preview not available for ${mimeType}. Use Open to download.`} />
        )}
      </div>
    </section>
  );
}

function Empty({ message }: { message: string }) {
  return (
    <div className="grid h-full place-items-center px-6 text-center text-2xs text-slate-400">
      {message}
    </div>
  );
}

function classify(mimeType: string): "pdf" | "image" | "other" {
  if (mimeType === "application/pdf") return "pdf";
  if (mimeType.startsWith("image/")) return "image";
  return "other";
}
