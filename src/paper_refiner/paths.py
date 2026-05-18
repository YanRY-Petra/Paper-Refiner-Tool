"""Repository root (contains prompts.yaml, config files)."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """``paper-refiner-tool/`` project root when installed editable from source."""
    return Path(__file__).resolve().parents[2]
