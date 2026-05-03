// Display formatters shared across invoice tables and detail surfaces.
// Centralised so currency symbol and placeholder rules stay consistent
// — Slice 103 unified "RM 1,234.56" rendering and the "—" placeholder
// for missing invoice numbers.

const CURRENCY_SYMBOL: Record<string, string> = {
  MYR: "RM",
};

export function formatMoney(
  code: string | null | undefined,
  amount: string | number | null | undefined,
): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return "—";
  const symbol = code ? (CURRENCY_SYMBOL[code] ?? code) : "";
  const formatted = n.toLocaleString("en-MY", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return symbol ? `${symbol} ${formatted}` : formatted;
}
