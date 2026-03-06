#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import subprocess
import sys
from pathlib import Path


def _local_venv_python() -> Path | None:
    """Return the local virtualenv interpreter path when available."""
    root = Path(__file__).resolve().parent
    if os.name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def _same_path(a: str, b: str) -> bool:
    try:
        a_path = str(Path(a).resolve())
    except OSError:
        a_path = os.path.abspath(a)
    try:
        b_path = str(Path(b).resolve())
    except OSError:
        b_path = os.path.abspath(b)
    return os.path.normcase(a_path) == os.path.normcase(b_path)


def _enforce_project_venv() -> None:
    """
    Ensure manage.py runs with this project's `.venv` interpreter.

    This prevents cross-project virtualenv issues (e.g., importing packages from
    another repository's venv).
    """
    if os.environ.get("ONEGROUP_SKIP_VENV_ENFORCEMENT") == "1":
        return

    venv_python = _local_venv_python()
    if not venv_python:
        return

    if _same_path(sys.executable, str(venv_python)):
        return

    # Prevent recursive re-exec loops.
    if os.environ.get("ONEGROUP_REEXEC") == "1":
        return

    env = os.environ.copy()
    env["ONEGROUP_REEXEC"] = "1"
    cmd = [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        code = subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


def main():
    """Run administrative tasks."""
    _enforce_project_venv()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "onegroup_platform.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
