#!/usr/bin/env python
"""Standard Django management entry point for the desktop sidecar.

The Electron main process doesn't call this — it calls
``run_sidecar.py`` which boots the WSGI app on a localhost port.
This file is here for the usual `python manage.py migrate` /
`python manage.py shell` developer ergonomics during Phase 3 work.
"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zk_desktop.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
