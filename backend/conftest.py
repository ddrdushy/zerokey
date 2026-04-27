"""Pytest configuration. Routes test runs to settings.test."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zerokey.settings.test")
