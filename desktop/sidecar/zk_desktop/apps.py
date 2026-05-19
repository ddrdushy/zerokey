"""App config for the sidecar shell.

We don't ship models — this AppConfig exists so Django can call
``ready()`` after all INSTALLED_APPS load. That's the safe moment to
monkeypatch ``apps.submission.certificates.ensure_certificate`` to
swap in the remote signer for intermediary orgs.
"""

from __future__ import annotations

from django.apps import AppConfig


class SidecarConfig(AppConfig):
    name = "zk_desktop"
    label = "zk_desktop"
    verbose_name = "ZeroKey Desktop Sidecar"

    def ready(self) -> None:
        # Late patch — by now apps.submission is registered + its
        # modules are importable.
        from zk_desktop import boot

        boot.install_remote_signer_for_intermediary()
