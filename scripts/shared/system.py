"""
Shared helpers for machine-local environment details.
"""

import getpass
import os


def current_user() -> str:
    """Return the current login name for Keychain lookups."""
    return os.environ.get("USER") or getpass.getuser()
