from __future__ import annotations

import sys

import pytest

MIN_PYTHON = (3, 12)


def pytest_configure(config) -> None:
    if sys.version_info < MIN_PYTHON:
        pytest.exit(
            "Python 3.12+ is required (same as Docker image python:3.12-slim). "
            "On Windows: .\\scripts\\setup-dev.ps1 or py -3.12 -m venv .venv. "
            f"Current: {sys.version.split()[0]} ({sys.executable})",
            returncode=2,
        )
