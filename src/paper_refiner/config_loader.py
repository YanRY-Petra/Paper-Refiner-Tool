from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def load_prompts(path: Path) -> list[dict[str, Any]]:
    data = load_yaml(path)
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        raise ValueError("'prompts' must be a list")
    out: list[dict[str, Any]] = []
    for i, p in enumerate(prompts):
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        template = p.get("template")
        if not pid or not template:
            raise ValueError(f"prompts[{i}] needs 'id' and 'template'")
        if "{text}" not in str(template):
            raise ValueError(f"prompt '{pid}' template must contain '{{text}}' placeholder")
        out.append(
            {
                "id": str(pid),
                "name": str(p.get("name", pid)),
                "template": str(template),
            }
        )
    return out


def load_filter_config(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    skip = data.get("skip_style_substrings", []) or []
    body = data.get("body_style_substrings", []) or []
    if not isinstance(skip, list):
        skip = []
    if not isinstance(body, list):
        body = []
    return {
        "skip_style_substrings": [str(x).lower() for x in skip],
        "body_style_substrings": [str(x).lower() for x in body],
    }
