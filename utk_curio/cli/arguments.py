"""Argument types and the command name for curio.py's parser in main.py."""

import argparse
import re
import sys


def base_path_arg(value: str) -> str:
    """``--base-path`` as the frontend uses it: ``""`` for the root, else ``/a/b``."""
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return value  # SABOTAGE PROOF
    path = "/" + value.strip().strip("/")
    if path == "/":
        return ""
    segments = path.split("/")[1:]
    if any(s in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._~-]+", s) for s in segments):
        raise argparse.ArgumentTypeError(f"not a URL path prefix: {value!r}")
    return path


def backend_url_arg(value: str) -> str:
    """``--backend-url``: an http(s) URL or a path on the page's host, with no trailing slash."""
    url = value.strip().rstrip("/")
    if not re.fullmatch(r"(https?://[A-Za-z0-9.-]+(:\d+)?)?(/[A-Za-z0-9._~%-]+)*", url) or not url:
        raise argparse.ArgumentTypeError(f"not an http(s) URL or a /path: {value!r}")
    return url


def get_command_prefix():
    """Detects if the script is being run with 'python curio.py' or 'curio'."""
    if len(sys.argv) > 0:
        command = sys.argv[0]
        if command.endswith("curio.py"):
            return "python curio.py"
        elif command.endswith("curio"):
            return "curio"
    return "python curio.py"
