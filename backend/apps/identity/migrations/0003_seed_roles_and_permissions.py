"""Seed the five v1 roles and the initial permission codes.

The role / permission catalog is system-defined in v1 (not editable by
customers). Custom roles are a P3 feature. The five roles below correspond
to USER_PERSONAS.md and DATA_MODEL.md:

  - Owner     — full control; only Owners can change billing or invite Owners
  - Admin     — full operational control except billing
  - Approver  — can approve invoices for submission
  - Submitter — can create and submit invoices
  - Viewer    — read-only access

Permission codes are namespaced ``domain.action`` strings. The catalog grows
as features land; new permissions are added via additional data migrations
so the audit trail of capability changes is intact.
"""

from __future__ import annotations

from django.db import migrations

# Initial v1 permission catalogue. New codes land via subsequent migrations.
PERMISSIONS: list[tuple[str, str]] = [
    # Identity
    ("identity.member.invite", "Invite a user to the organization"),
    ("identity.member.remove", "Remove a member from the organization"),
    ("identity.member.role.change", "Change a member's role"),
    ("identity.organization.update", "Edit organization settings"),
    # Invoice lifecycle
    ("invoice.create", "Create an invoice draft"),
    ("invoice.submit", "Submit an invoice for approval / signing"),
    ("invoice.approve", "Approve an invoice for submission to LHDN"),
    ("invoice.cancel", "Cancel a submitted invoice within the LHDN window"),
    ("invoice.read", "View invoices"),
    # Customer master
    ("customer_master.read", "View customer master records"),
    ("customer_master.write", "Create or modify customer master records"),
    # Audit
    ("audit.read", "View the audit log"),
    ("audit.export", "Export the audit log as a verifiable bundle"),
    # Billing
    ("billing.read", "View billing information"),
    ("billing.write", "Manage subscription, payment methods, and plans"),
    # Settings
    ("settings.read", "View organization settings"),
    ("settings.write", "Modify organization settings"),
    # Certificates
    ("certificate.upload", "Upload or rotate the LHDN signing certificate"),
]


# Mapping of role name → set of permission codes.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": {p[0] for p in PERMISSIONS},  # everything
    "admin": {p[0] for p in PERMISSIONS} - {"billing.write"},
    "approver": {
        "invoice.read",
        "invoice.approve",
        "invoice.cancel",
        "customer_master.read",
        "audit.read",
        "settings.read",
    },
    "submitter": {
        "invoice.create",
        "invoice.submit",
        "invoice.read",
        "customer_master.read",
        "customer_master.write",
        "settings.read",
    },
    "viewer": {
        "invoice.read",
        "customer_master.read",
        "audit.read",
        "settings.read",
        "billing.read",
    },
}


ROLE_DESCRIPTIONS: dict[str, str] = {
    "owner": "Full control. Only Owners can change billing or invite other Owners.",
    "admin": "Full operational control. Cannot change billing.",
    "approver": "Approves invoices for submission. Read-only on customer master.",
    "submitter": "Creates and submits invoices. Cannot approve or change billing.",
    "viewer": "Read-only access. Sees invoices, customer master, audit log.",
}


def seed_roles_and_permissions(apps, schema_editor):  # noqa: ARG001
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")

    permissions_by_code = {}
    for code, description in PERMISSIONS:
        perm, _ = Permission.objects.get_or_create(
            code=code, defaults={"description": description}
        )
        permissions_by_code[code] = perm

    for role_name, perm_codes in ROLE_PERMISSIONS.items():
        role, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={
                "description": ROLE_DESCRIPTIONS[role_name],
                "is_system": True,
            },
        )
        role.permissions.set([permissions_by_code[code] for code in perm_codes])


def reverse_seed(apps, schema_editor):  # noqa: ARG001
    Role = apps.get_model("identity", "Role")
    Permission = apps.get_model("identity", "Permission")
    Role.objects.filter(name__in=ROLE_PERMISSIONS.keys()).delete()
    Permission.objects.filter(code__in=[p[0] for p in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0002_rls_policies"),
    ]

    operations = [
        migrations.RunPython(seed_roles_and_permissions, reverse_seed),
    ]
