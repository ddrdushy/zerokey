"use client";

// Slice 87 — Approvals queue. The approver sees a list of
// invoices awaiting their decision; from each row they can
// approve (with optional note) or reject (with required reason).
// Rows redirect to the invoice detail for full review before
// the gesture.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { formatMoney } from "@/lib/format";

type PendingApproval = {
  approval_id: string;
  invoice_id: string;
  invoice_number: string;
  grand_total: string | null;
  currency_code: string;
  buyer_legal_name: string;
  requested_by_user_id: string;
  requested_at: string;
  requested_reason: string;
};

export default function ApprovalsPage() {
  const router = useRouter();
  const [rows, setRows] = useState<PendingApproval[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setRows(await api.listPendingApprovals());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.replace("/sign-in");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setRows([]);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onApprove(approvalId: string) {
    const note = window.prompt("Optional approval note (or leave blank):") ?? "";
    setBusyId(approvalId);
    try {
      await api.approveInvoice(approvalId, note);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approve failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function onReject(approvalId: string) {
    const reason = window.prompt("Reason for rejection (required):");
    if (!reason || !reason.trim()) return;
    setBusyId(approvalId);
    try {
      await api.rejectInvoice(approvalId, reason);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reject failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">Approvals</h1>
            <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
              Invoices waiting on your decision
            </p>
          </div>
          {rows && rows.length > 0 && (
            <span className="text-2xs uppercase tracking-wider text-slate-400">
              {rows.length} pending
            </span>
          )}
        </header>

        {error && (
          <div className="rounded-md border border-error bg-error/5 px-4 py-2 text-2xs text-error">
            {error}
          </div>
        )}

        {rows === null ? (
          <Skeleton />
        ) : rows.length === 0 ? (
          <Empty />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-100 bg-white">
            <table className="w-full text-2xs">
              <thead className="bg-slate-50 text-slate-400">
                <tr>
                  <Th>Invoice</Th>
                  <Th>Buyer</Th>
                  <Th align="right">Amount</Th>
                  <Th>Requested</Th>
                  <Th>Reason</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((row) => (
                  <tr key={row.approval_id} className="hover:bg-slate-50">
                    <td className="px-3 py-3">
                      <Link
                        href={`/dashboard/invoices/${row.invoice_id}`}
                        className="font-medium text-ink hover:underline"
                      >
                        {row.invoice_number || <span className="text-slate-400">—</span>}
                      </Link>
                    </td>
                    <td className="px-3 py-3 text-slate-600">{row.buyer_legal_name || "—"}</td>
                    <td className="px-3 py-3 text-right font-mono">
                      {formatMoney(row.currency_code, row.grand_total)}
                    </td>
                    <td className="px-3 py-3 text-slate-600">
                      {new Date(row.requested_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-3 text-slate-600">
                      {row.requested_reason || <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onReject(row.approval_id)}
                        disabled={busyId === row.approval_id}
                      >
                        <XCircle className="mr-1 h-3.5 w-3.5" /> Reject
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => onApprove(row.approval_id)}
                        disabled={busyId === row.approval_id}
                        className="ml-2"
                      >
                        <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Approve
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={
        "px-3 py-2 font-medium uppercase tracking-wider " +
        (align === "right" ? "text-right" : "text-left")
      }
    >
      {children}
    </th>
  );
}

function Skeleton() {
  return (
    <div className="grid place-items-center py-24 text-2xs uppercase tracking-wider text-slate-400">
      Loading…
    </div>
  );
}

function Empty() {
  return (
    <section className="rounded-xl border border-slate-100 bg-white p-12 text-center">
      <ShieldCheck className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
      <h2 className="mt-4 font-display text-xl font-semibold">No approvals waiting</h2>
      <p className="mx-auto mt-2 max-w-md text-2xs text-slate-500">
        When a submitter requests approval for an invoice, it will appear here for owners, admins,
        and approvers to review.
      </p>
    </section>
  );
}
