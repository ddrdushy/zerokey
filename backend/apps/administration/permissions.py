"""Permission classes for the platform-administration surface.

Distinct from tenant-scoped permissions (which live on individual app
views and check ``request.user`` against the active organization). The
super-admin surface bypasses tenant scoping entirely — it's the
operator's view across every customer.

We piggyback on Django's built-in ``User.is_staff`` flag rather than
introducing a third role tier:

  - ``is_staff = True``  → platform operator (this codebase's
    super-admin). Set manually on the User row by ``createsuperuser`` or
    via the Django admin.
  - ``is_staff = False`` → customer. The vast majority of users.

There's also Django's ``is_superuser`` flag, which we leave aligned with
``is_staff`` (the model manager keeps them in lockstep). The semantic
difference matters for Django's own admin permission system but not for
our app-level surface — we treat ``is_staff`` as the single truth.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsPlatformStaff(BasePermission):
    """Allow only authenticated users with ``is_staff = True``.

    Returns 403 (not 404) on a non-staff request. The frontend uses 403
    as the "redirect to /dashboard, this isn't your route" signal — same
    contract as a tenant trying to access another tenant's row.
    """

    message = "Platform-staff access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return bool(getattr(user, "is_staff", False))
