"use client";

// Inline MSIC code suggestion for ItemMaster rows (Slice 94).
//
// When an item has no ``default_msic_code``, this component fetches
// the top suggestions from /msic/suggest/?q=<canonical_name> and lets
// the user apply one with a single click. The suggestion endpoint
// returns at most 5 candidates ranked by token-overlap; we show the
// top one inline with an "(N more)" affordance to expand the rest.

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { api, type Item } from "@/lib/api";
import { cn } from "@/lib/utils";

type Suggestion = {
  code: string;
  description_en: string;
  description_bm: string;
  score: number;
};

export function MsicSuggestion({
  item,
  onApplied,
}: {
  item: Item;
  onApplied: (code: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fetchSuggestions() {
    if (suggestions != null) return; // already loaded
    setLoading(true);
    setError(null);
    try {
      const result = await api.suggestMsic(item.canonical_name);
      setSuggestions(result.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't fetch suggestions.");
    } finally {
      setLoading(false);
    }
  }

  async function apply(code: string) {
    setApplying(code);
    setError(null);
    try {
      await api.updateItem(item.id, { default_msic_code: code });
      onApplied(code);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't apply code.");
    } finally {
      setApplying(null);
    }
  }

  if (suggestions == null) {
    return (
      <button
        type="button"
        onClick={fetchSuggestions}
        disabled={loading}
        className={cn(
          "inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-2xs font-medium text-slate-600 hover:border-ink hover:text-ink",
          loading && "opacity-60",
        )}
        title="Find a likely MSIC code based on the item description"
      >
        <Sparkles className="h-3 w-3" />
        {loading ? "Searching…" : "Suggest"}
      </button>
    );
  }

  if (suggestions.length === 0) {
    return (
      <span className="text-2xs italic text-slate-400">
        No match — pick from /help/msic
      </span>
    );
  }

  const top = suggestions[0];
  const rest = suggestions.slice(1);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => apply(top.code)}
          disabled={applying != null}
          className="rounded-md border border-success/40 bg-success/5 px-2 py-1 font-mono text-2xs text-success hover:border-success"
          title={`Apply ${top.code} — ${top.description_en}`}
        >
          {applying === top.code ? "Applying…" : `Use ${top.code}`}
        </button>
        <span className="truncate text-2xs text-slate-500" title={top.description_en}>
          {top.description_en}
        </span>
      </div>
      {rest.length > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start text-[10px] uppercase tracking-wider text-slate-400 hover:text-ink"
        >
          {expanded ? "Hide" : `${rest.length} more`}
        </button>
      )}
      {expanded && (
        <ul className="flex flex-col gap-1 pl-1">
          {rest.map((s) => (
            <li key={s.code} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => apply(s.code)}
                disabled={applying != null}
                className="rounded-md border border-slate-200 bg-white px-2 py-0.5 font-mono text-2xs text-slate-600 hover:border-ink"
              >
                {applying === s.code ? "…" : s.code}
              </button>
              <span className="truncate text-2xs text-slate-500" title={s.description_en}>
                {s.description_en}
              </span>
            </li>
          ))}
        </ul>
      )}
      {error && <span className="text-[10px] text-error">{error}</span>}
    </div>
  );
}
