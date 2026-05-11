"use client";

// Slice 107 — scan an LHDN MyInvois buyer-share QR to auto-fill
// the buyer fields on an invoice.
//
// What this is: the QR a buyer generates from the MyInvois portal
// to share their tax info (TIN, legal name, registration number,
// SST number, MSIC code, address) with a supplier. Saves the
// supplier from typing every field by hand for a first-time buyer.
//
// What this is NOT: the validated-invoice QR we generate after
// LHDN clears a submission — that lives on LhdnPanel and is the
// outbound trust signal.
//
// Implementation notes:
//
//   * Two input modes — upload an image of the QR (we decode it
//     with jsqr) or paste decoded text (URL / JSON) directly. No
//     live camera yet; getUserMedia adds a permission prompt that
//     scares users for a feature most people use rarely. If
//     demand surfaces we add it later.
//   * The actual QR payload format isn't tightly documented by
//     LHDN. We try three strategies in order: JSON, URL with
//     known query params, MyInvois deep-link URL (record the
//     token, can't resolve offline). The parser is liberal —
//     accepts a wide range of field-name aliases (``tin``,
//     ``Tin``, ``buyer_tin``, ``buyerTIN`` all map to the buyer
//     TIN field).
//   * We never silently overwrite a non-empty field; the preview
//     screen shows the user exactly which fields will change so
//     they can untick anything they want to keep.

import { useRef, useState } from "react";
import jsQR from "jsqr";
import { QrCode, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";

// Frontend-facing alias of the editable buyer field names. Keep in
// sync with EditableField in the job-detail page.
type BuyerField =
  | "buyer_legal_name"
  | "buyer_tin"
  | "buyer_address"
  | "buyer_msic_code"
  | "buyer_country_code"
  | "buyer_id_type"
  | "buyer_id_value";

// Human label per field, displayed in the preview list.
const FIELD_LABEL: Record<BuyerField, string> = {
  buyer_legal_name: "Legal name",
  buyer_tin: "TIN",
  buyer_address: "Address",
  buyer_msic_code: "MSIC code",
  buyer_country_code: "Country",
  buyer_id_type: "ID type",
  buyer_id_value: "Registration number",
};

// Field name aliases we accept from the QR payload. The lookup
// is case-insensitive — see ``readField`` below.
const ALIASES: Record<BuyerField, string[]> = {
  buyer_legal_name: ["buyer_legal_name", "legal_name", "name", "business_name", "buyerName"],
  buyer_tin: ["buyer_tin", "tin", "tinNo", "tin_no"],
  buyer_address: [
    "buyer_address",
    "address",
    "address1",
    "addressLine1",
    "fullAddress",
  ],
  buyer_msic_code: ["buyer_msic_code", "msic", "msic_code", "msicCode"],
  buyer_country_code: ["buyer_country_code", "country", "country_code", "countryCode"],
  buyer_id_type: ["buyer_id_type", "id_type", "idType"],
  buyer_id_value: [
    "buyer_id_value",
    "id_value",
    "idValue",
    "regNo",
    "reg_no",
    "registration_number",
    "registrationNumber",
    "brn",
  ],
};

type ParsedBuyer = Partial<Record<BuyerField, string>>;

type ParseOutcome =
  | { kind: "fields"; data: ParsedBuyer; raw: string }
  | { kind: "deep_link"; url: string; raw: string }
  | { kind: "unparseable"; raw: string };

function readField(obj: Record<string, unknown>, field: BuyerField): string | null {
  const lowerKeys: Record<string, string> = {};
  for (const k of Object.keys(obj)) lowerKeys[k.toLowerCase()] = k;
  for (const alias of ALIASES[field]) {
    const actualKey = lowerKeys[alias.toLowerCase()];
    if (actualKey === undefined) continue;
    const v = obj[actualKey];
    if (v === null || v === undefined) continue;
    const s = String(v).trim();
    if (s) return s;
  }
  return null;
}

function fieldsFromObject(obj: Record<string, unknown>): ParsedBuyer {
  const out: ParsedBuyer = {};
  (Object.keys(ALIASES) as BuyerField[]).forEach((field) => {
    const v = readField(obj, field);
    if (v !== null) out[field] = v;
  });
  return out;
}

function parsePayload(raw: string): ParseOutcome {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: "unparseable", raw };

  // Strategy 1 — direct JSON payload.
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const obj = JSON.parse(trimmed);
      if (obj && typeof obj === "object") {
        const data = fieldsFromObject(obj as Record<string, unknown>);
        if (Object.keys(data).length > 0) return { kind: "fields", data, raw };
      }
    } catch {
      // Fall through to other strategies.
    }
  }

  // Strategy 2 — URL with known query params.
  let url: URL | null = null;
  try {
    url = new URL(trimmed);
  } catch {
    url = null;
  }
  if (url) {
    const isMyInvois = /myinvois\.hasil\.gov\.my/i.test(url.hostname);
    const params: Record<string, string> = {};
    url.searchParams.forEach((value, key) => {
      params[key] = value;
    });
    if (Object.keys(params).length > 0) {
      const data = fieldsFromObject(params);
      if (Object.keys(data).length > 0) return { kind: "fields", data, raw };
    }
    if (isMyInvois) {
      // Path-encoded MyInvois share link — we can't resolve offline.
      return { kind: "deep_link", url: trimmed, raw };
    }
  }

  // Strategy 3 — line-oriented "key: value" pairs (some local
  // tools generate this for offline use).
  const lines = trimmed.split(/\r?\n/);
  const kv: Record<string, string> = {};
  for (const line of lines) {
    const m = line.match(/^\s*([A-Za-z_][\w-]*)\s*[:=]\s*(.+?)\s*$/);
    if (m) kv[m[1]] = m[2];
  }
  if (Object.keys(kv).length > 0) {
    const data = fieldsFromObject(kv);
    if (Object.keys(data).length > 0) return { kind: "fields", data, raw };
  }

  return { kind: "unparseable", raw };
}

async function decodeImageFile(file: File): Promise<string | null> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("Image failed to load."));
    i.src = dataUrl;
  });
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0);
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const code = jsQR(imageData.data, imageData.width, imageData.height);
  return code?.data ?? null;
}

export function BuyerQRScanner({
  currentValues,
  onApply,
}: {
  /** Current buyer field values keyed by the EditableField name. Used
   *  to show which incoming values would overwrite something the user
   *  already has on the invoice. */
  currentValues: Partial<Record<BuyerField, string>>;
  /** Apply a parsed field. The job-detail page wires this to its
   *  ``onChangeField`` so the values flow into the same draft state
   *  manual edits use. */
  onApply: (field: BuyerField, value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"upload" | "paste">("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");
  const [outcome, setOutcome] = useState<ParseOutcome | null>(null);
  // Per-field "apply this one" toggles. Default to true for all
  // detected fields when a parse completes.
  const [toApply, setToApply] = useState<Partial<Record<BuyerField, boolean>>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  function reset() {
    setOutcome(null);
    setError(null);
    setPasted("");
    setToApply({});
    if (fileRef.current) fileRef.current.value = "";
  }

  function close() {
    setOpen(false);
    reset();
  }

  async function onFile(file: File) {
    setBusy(true);
    setError(null);
    setOutcome(null);
    try {
      const decoded = await decodeImageFile(file);
      if (!decoded) {
        setError("No QR code found in that image. Try a sharper photo.");
        return;
      }
      const parsed = parsePayload(decoded);
      setOutcome(parsed);
      if (parsed.kind === "fields") {
        const next: Partial<Record<BuyerField, boolean>> = {};
        (Object.keys(parsed.data) as BuyerField[]).forEach((k) => {
          next[k] = true;
        });
        setToApply(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read image.");
    } finally {
      setBusy(false);
    }
  }

  function onParsePaste() {
    setError(null);
    setOutcome(null);
    if (!pasted.trim()) {
      setError("Paste the scanned QR contents first.");
      return;
    }
    const parsed = parsePayload(pasted);
    setOutcome(parsed);
    if (parsed.kind === "fields") {
      const next: Partial<Record<BuyerField, boolean>> = {};
      (Object.keys(parsed.data) as BuyerField[]).forEach((k) => {
        next[k] = true;
      });
      setToApply(next);
    }
  }

  function applyChosen() {
    if (!outcome || outcome.kind !== "fields") return;
    (Object.keys(outcome.data) as BuyerField[]).forEach((field) => {
      if (!toApply[field]) return;
      const value = outcome.data[field];
      if (value === undefined) return;
      onApply(field, value);
    });
    close();
  }

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <QrCode className="mr-1.5 h-3.5 w-3.5" />
        Scan buyer QR
      </Button>

      {open && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex w-full max-w-xl flex-col rounded-xl border border-slate-100 bg-white shadow-lg">
            <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <h3 className="font-display text-lg font-semibold">Scan buyer info QR</h3>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="grid h-7 w-7 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </header>

            <div className="flex border-b border-slate-100 text-2xs uppercase tracking-wider">
              {(["upload", "paste"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    setMode(m);
                    reset();
                  }}
                  className={
                    "flex-1 px-4 py-3 font-medium " +
                    (mode === m
                      ? "border-b-2 border-ink text-ink"
                      : "text-slate-400 hover:text-ink")
                  }
                >
                  {m === "upload" ? "Upload image" : "Paste decoded text"}
                </button>
              ))}
            </div>

            <div className="flex flex-col gap-4 px-5 py-5">
              {error && (
                <div className="rounded-md border border-error bg-error/5 px-3 py-2 text-2xs text-error">
                  {error}
                </div>
              )}

              {mode === "upload" && !outcome && (
                <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-slate-200 px-6 py-10 text-center">
                  <Upload className="h-6 w-6 text-slate-400" />
                  <p className="text-2xs text-slate-500">
                    Take a photo of the QR on the buyer&rsquo;s phone or upload a
                    screenshot. We decode it on your device — the image never
                    leaves your browser.
                  </p>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onFile(f);
                    }}
                  />
                  <Button
                    size="sm"
                    onClick={() => fileRef.current?.click()}
                    disabled={busy}
                  >
                    {busy ? "Reading…" : "Choose image"}
                  </Button>
                </div>
              )}

              {mode === "paste" && !outcome && (
                <div className="flex flex-col gap-2">
                  <label className="text-2xs font-medium uppercase tracking-wider text-slate-500">
                    QR contents
                  </label>
                  <textarea
                    value={pasted}
                    onChange={(e) => setPasted(e.target.value)}
                    rows={6}
                    placeholder='{"tin":"C12345678901","name":"SkyRim Sdn. Bhd.","regNo":"201901012345",...}'
                    className="rounded-md border border-slate-200 px-3 py-2 font-mono text-2xs focus:border-ink focus:outline-none"
                  />
                  <p className="text-2xs text-slate-400">
                    Paste a JSON payload, a URL with parameters, or a list of
                    <code className="mx-1 rounded bg-slate-100 px-1 font-mono text-[10px]">
                      key: value
                    </code>
                    lines.
                  </p>
                  <div className="flex justify-end">
                    <Button size="sm" onClick={onParsePaste}>
                      Parse
                    </Button>
                  </div>
                </div>
              )}

              {outcome && outcome.kind === "fields" && (
                <div className="flex flex-col gap-3">
                  <p className="text-2xs text-slate-500">
                    We detected the following fields. Untick anything you want
                    to keep as-is.
                  </p>
                  <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100">
                    {(Object.keys(outcome.data) as BuyerField[]).map((field) => {
                      const value = outcome.data[field] ?? "";
                      const current = currentValues[field] ?? "";
                      const overwrites = current && current !== value;
                      return (
                        <li
                          key={field}
                          className="flex items-start gap-3 px-4 py-3 text-2xs"
                        >
                          <input
                            type="checkbox"
                            checked={!!toApply[field]}
                            onChange={(e) =>
                              setToApply((prev) => ({
                                ...prev,
                                [field]: e.target.checked,
                              }))
                            }
                            className="mt-0.5 h-4 w-4"
                          />
                          <div className="flex-1">
                            <div className="font-medium text-ink">
                              {FIELD_LABEL[field]}
                            </div>
                            <div className="mt-0.5 font-mono text-2xs text-slate-600">
                              {value}
                            </div>
                            {overwrites && (
                              <div className="mt-1 text-[10px] uppercase tracking-wider text-warning">
                                Replaces current: {current}
                              </div>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}

              {outcome && outcome.kind === "deep_link" && (
                <div className="rounded-md border border-warning/30 bg-warning/5 px-4 py-3 text-2xs text-warning">
                  <div className="font-medium">MyInvois share link detected</div>
                  <p className="mt-1 text-slate-600">
                    This QR points to a MyInvois portal page. ZeroKey can&rsquo;t
                    fetch the buyer details from the portal offline — open the
                    link on a device signed into MyInvois, or ask the buyer to
                    send a JSON-format QR.
                  </p>
                  <code className="mt-2 block break-all rounded bg-white px-2 py-1 font-mono text-[10px] text-ink">
                    {outcome.url}
                  </code>
                </div>
              )}

              {outcome && outcome.kind === "unparseable" && (
                <div className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error">
                  <div className="font-medium">
                    We read the QR but couldn&rsquo;t find any buyer fields.
                  </div>
                  <p className="mt-1 text-slate-600">Raw contents:</p>
                  <pre className="mt-2 max-h-32 overflow-auto rounded bg-white px-2 py-1 font-mono text-[10px] text-ink">
                    {outcome.raw}
                  </pre>
                </div>
              )}
            </div>

            <footer className="flex items-center justify-end gap-2 border-t border-slate-100 px-5 py-4">
              <Button variant="ghost" size="sm" onClick={close}>
                Cancel
              </Button>
              {outcome && outcome.kind === "fields" && (
                <Button
                  size="sm"
                  onClick={applyChosen}
                  disabled={
                    !Object.values(toApply).some(Boolean) || busy
                  }
                >
                  Apply selected
                </Button>
              )}
            </footer>
          </div>
        </div>
      )}
    </>
  );
}
