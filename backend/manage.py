#!/usr/bin/env python
"""Django administrative entry point."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zerokey.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django. Are you in the right virtualenv?") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
