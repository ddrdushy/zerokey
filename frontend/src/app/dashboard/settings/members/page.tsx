"use client";

// Settings → Members tab. Lists every member of the active org with
// role + active/inactive state + join date. Owners + admins can
// change other members' roles + toggle active. The "current user"
// row is read-only — self-changes go through a different (future)
// profile flow so an owner can't accidentally lock themselves out.

import { useEffect, useState } from "react";
import { Copy, MoreHorizontal, UserPlus, Users, X } from "lucide-react";

import {
  api,
  ApiError,
  type InvitationRow,
  type Me,
  type OrganizationMemberRow,
} from "@/lib/api";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { cn } from "@/lib/utils";

const ROLE_OPTIONS = ["owner", "admin", "approver", "submitter", "viewer"];

export default function MembersSettingsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [members, setMembers] = useState<OrganizationMemberRow[] | null>(null);
  const [invitations, setInvitations] = useState<InvitationRow[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showInviteForm, setShowInviteForm] = useState(false);
  const [lastIssuedLink, setLastIssuedLink] = useState<string | null>(null);

  async function refresh() {
    try {
      const [list, invites] = await Promise.all([
        api.listOrganizationMembers(),
        api.listInvitations().catch(() => []),
      ]);
      setMembers(list);
      setInvitations(invites);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You are not a member of this organization.");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
      setMembers([]);
    }
  }

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    refresh();
  }, []);

  // Caller's role determines what actions render. Anything below admin
  // gets a read-only view. Owners can promote/demote anyone; admins can
  // change non-owner rows. While `me` is loading the role is unknown —
  // we render WITHOUT actions but also without the "read-only" hint so
  // the user doesn't see a flash of the wrong state.
  const myRole = me
    ? (me.memberships.find((m) => m.organization.id === me.active_organization_id)
        ?.role.name ?? null)
    : null;
  const canManage = myRole === "owner" || myRole === "admin";

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <header>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Settings
          </h1>
          <p className="mt-1 text-2xs uppercase tracking-wider text-slate-400">
            Organization, members, and platform integrations
          </p>
        </header>
        <SettingsTabs />

        {error && (
          <div
            role="alert"
            className="rounded-md border border-error bg-error/5 px-4 py-3 text-2xs text-error"
          >
            {error}
          </div>
        )}

        <section className="rounded-xl border border-slate-100 bg-white">
          <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-ink">
                Members ({members?.length ?? 0})
              </h2>
            </div>
            <div className="flex items-center gap-3">
              {myRole !== null && !canManage && (
                <span className="text-[10px] uppercase tracking-wider text-slate-400">
                  Read-only · ask an owner or admin to make changes
                </span>
              )}
              {canManage && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowInviteForm((s) => !s)}
                >
                  <UserPlus className="mr-1.5 h-3.5 w-3.5" />
                  Invite member
                </Button>
              )}
            </div>
          </header>

          {showInviteForm && canManage && (
            <InviteForm
              onIssued={(url) => {
                setLastIssuedLink(url);
                setShowInviteForm(false);
                refresh();
              }}
              onCancel={() => setShowInviteForm(false)}
              onError={setError}
            />
          )}

          {lastIssuedLink && (
            <InviteLinkPanel
              url={lastIssuedLink}
              onDismiss={() => setLastIssuedLink(null)}
            />
          )}

          {members === null ? (
            <Loading />
          ) : members.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="divide-y divide-slate-100">
              {members.map((m) => {
                const isMe = me?.id === m.user_id;
                const isOwnerRow = m.role === "owner";
                const canEditThisRow =
                  canManage &&
                  !isMe &&
                  !(myRole === "admin" && isOwnerRow);
                return (
                  <li
                    key={m.id}
                    className={cn(
                      "flex flex-col gap-2 px-5 py-3 text-2xs",
                      !m.is_active && "opacity-60",
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex-1 truncate">
                        <span className="font-medium text-ink">{m.email}</span>
                        {isMe && (
                          <span className="ml-2 rounded-sm bg-signal/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-ink">
                            You
                          </span>
                        )}
                        {!m.is_active && (
                          <span className="ml-2 rounded-sm bg-slate-200 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">
                            Inactive
                          </span>
                        )}
                      </div>
                      <span className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                        {m.role}
                      </span>
                      <span className="text-[10px] text-slate-400">
                        {m.joined_date
                          ? new Date(m.joined_date).toLocaleDateString()
                          : ""}
                      </span>
                      {canEditThisRow && (
                        <button
                          type="button"
                          aria-label="Member actions"
                          onClick={() =>
                            setEditing(editing === m.id ? null : m.id)
                          }
                          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-ink"
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    {editing === m.id && myRole && (
                      <MemberActions
                        member={m}
                        myRole={myRole}
                        onClose={() => setEditing(null)}
                        onChanged={() => {
                          setEditing(null);
                          refresh();
                        }}
                        onError={setError}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {invitations.filter((i) => i.status === "pending").length > 0 && (
          <section className="rounded-xl border border-slate-100 bg-white">
            <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <h2 className="text-sm font-semibold text-ink">
                Pending invitations ({
                  invitations.filter((i) => i.status === "pending").length
                })
              </h2>
            </header>
            <ul className="divide-y divide-slate-100">
              {invitations
                .filter((i) => i.status === "pending")
                .map((inv) => (
                  <li
                    key={inv.id}
                    className="flex items-center justify-between gap-3 px-5 py-3 text-2xs"
                  >
                    <div className="flex-1 truncate">
                      <span className="font-medium text-ink">{inv.email}</span>
                      <span className="ml-2 rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                        {inv.role}
                      </span>
                      <span className="ml-2 text-[10px] text-slate-400">
                        expires{" "}
                        {inv.expires_at
                          ? new Date(inv.expires_at).toLocaleDateString()
                          : ""}
                      </span>
                    </div>
                    {canManage && (
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await api.revokeInvitation(inv.id);
                            refresh();
                          } catch (err) {
                            setError(
                              err instanceof Error ? err.message : "Revoke failed.",
                            );
                          }
                        }}
                        className="rounded-md p-1 text-slate-400 hover:bg-error/5 hover:text-error"
                        aria-label="Revoke invitation"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </li>
                ))}
            </ul>
          </section>
        )}
      </div>
    </AppShell>
  );
}

function InviteForm({
  onIssued,
  onCancel,
  onError,
}: {
  onIssued: (invitationUrl: string) => void;
  onCancel: () => void;
  onError: (msg: string | null) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    onError(null);
    try {
      const result = await api.createInvitation(email.trim(), role);
      onIssued(result.invitation_url);
      setEmail("");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Invite failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-end gap-3 border-b border-slate-100 bg-slate-50/40 px-5 py-4"
    >
      <label className="flex flex-col gap-1 text-2xs">
        <span className="font-medium text-ink">Email</span>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="newmember@example.com"
          className="w-72 rounded-md border border-slate-200 bg-white px-2 py-1 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        />
      </label>
      <label className="flex flex-col gap-1 text-2xs">
        <span className="font-medium text-ink">Role</span>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-md border border-slate-200 bg-white px-2 py-1 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <Button size="sm" type="submit" disabled={submitting || !email.trim()}>
        {submitting ? "Inviting…" : "Send invite"}
      </Button>
      <Button
        size="sm"
        type="button"
        variant="ghost"
        onClick={onCancel}
        disabled={submitting}
      >
        Cancel
      </Button>
      <p className="ml-auto max-w-xs text-[10px] text-slate-400">
        We&apos;ll email the invite. The link is also shown once after issue
        in case email isn&apos;t configured.
      </p>
    </form>
  );
}

function InviteLinkPanel({
  url,
  onDismiss,
}: {
  url: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="border-b border-slate-100 bg-success/5 px-5 py-4 text-2xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-ink">
            Invitation issued · this link is shown once
          </p>
          <p className="mt-1 text-[10px] text-slate-500">
            We&apos;ve emailed it to the recipient. If you need to share it via
            another channel, copy now — it won&apos;t be displayed again.
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-ink"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <code className="flex-1 truncate rounded-md border border-slate-200 bg-white px-2 py-1 font-mono text-[10px] text-ink">
          {url}
        </code>
        <Button
          size="sm"
          variant="ghost"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            } catch {
              // Older browsers — user can select + copy manually.
            }
          }}
        >
          <Copy className="mr-1.5 h-3.5 w-3.5" />
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

function MemberActions({
  member,
  myRole,
  onClose,
  onChanged,
  onError,
}: {
  member: OrganizationMemberRow;
  myRole: string;
  onClose: () => void;
  onChanged: () => void;
  onError: (msg: string | null) => void;
}) {
  const [role, setRole] = useState(member.role);
  const [saving, setSaving] = useState(false);

  // Admins can't promote anyone to owner. Restrict the dropdown
  // accordingly so the operator doesn't pick a role we'll then
  // reject server-side.
  const eligibleRoles = ROLE_OPTIONS.filter(
    (r) => myRole === "owner" || r !== "owner",
  );

  async function applyChange(changes: {
    is_active?: boolean;
    role_name?: string;
  }) {
    setSaving(true);
    onError(null);
    try {
      await api.patchOrganizationMember(member.id, changes);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Update failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="mb-2 text-[11px] text-slate-500">
        Role + access changes are recorded on the audit log.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-md border border-slate-200 bg-white px-2 py-1 text-2xs text-ink focus:outline-none focus:ring-1 focus:ring-ink"
        >
          {eligibleRoles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="ghost"
          disabled={saving || role === member.role}
          onClick={() => applyChange({ role_name: role })}
        >
          Save role
        </Button>
        {member.is_active ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={saving}
            onClick={() => applyChange({ is_active: false })}
            className="text-error hover:bg-error/5"
          >
            Deactivate
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            disabled={saving}
            onClick={() => applyChange({ is_active: true })}
            className="text-success hover:bg-success/5"
          >
            Reactivate
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid place-items-center px-5 py-12 text-2xs uppercase tracking-wider text-slate-400">
      Loading members…
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid place-items-center px-5 py-12 text-center">
      <Users className="h-6 w-6 text-slate-300" aria-hidden />
      <p className="mt-2 text-2xs text-slate-500">
        No members yet. Use{" "}
        <span className="font-medium text-ink">Invite member</span> above to
        add teammates.
      </p>
    </div>
  );
}
