"use client";

// Settings → Members tab. Lists every member of the active org with
// role + active/inactive state + join date. Owners + admins can
// change other members' roles + toggle active. The "current user"
// row is read-only — self-changes go through a different (future)
// profile flow so an owner can't accidentally lock themselves out.

import { useEffect, useState } from "react";
import { MoreHorizontal, Users } from "lucide-react";

import {
  api,
  ApiError,
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
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const list = await api.listOrganizationMembers();
      setMembers(list);
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
            {myRole !== null && !canManage && (
              <span className="text-[10px] uppercase tracking-wider text-slate-400">
                Read-only · ask an owner or admin to make changes
              </span>
            )}
          </header>

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
      </div>
    </AppShell>
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
        No members yet. Sign up flow creates one membership; invitations
        for additional members ship in a follow-up.
      </p>
    </div>
  );
}
