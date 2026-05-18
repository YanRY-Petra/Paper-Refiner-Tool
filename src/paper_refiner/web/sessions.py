from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from paper_refiner.scan import ParagraphInfo

META_NAME = "meta.json"


def _sessions_base() -> Path:
    base = Path(__file__).resolve().parent / "_session_data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def new_session_id() -> str:
    return str(uuid.uuid4())


def session_dir(session_id: str) -> Path:
    if not session_id or len(session_id) > 64:
        raise ValueError("invalid session")
    # uuid only contains hex and hyphens
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    if safe != session_id:
        raise ValueError("invalid session")
    return _sessions_base() / session_id


def create_session(
    original_bytes: bytes,
    infos: list[ParagraphInfo],
    *,
    original_filename: str | None = None,
) -> str:
    sid = new_session_id()
    d = session_dir(sid)
    d.mkdir(parents=True, exist_ok=False)
    (d / "original.docx").write_bytes(original_bytes)
    eligible = [i.index for i in infos if i.skip_reason is None]
    meta = {
        "paragraphs": [asdict(p) for p in infos],
        "eligible_indices": eligible,
        "selected_indices": [],
        "refine_options": {
            "prompt_id": None,
            "temperature": 0.7,
            "model": None,
        },
        "last_results": [],
        "original_filename": original_filename or "document.docx",
    }
    (d / META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return sid


def save_meta(session_id: str, meta: dict[str, Any]) -> None:
    p = session_dir(session_id) / META_NAME
    if not p.parent.is_dir():
        raise FileNotFoundError("session not found")
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def update_meta(session_id: str, **patch: Any) -> dict[str, Any]:
    meta = load_meta(session_id)
    for key, value in patch.items():
        meta[key] = value
    save_meta(session_id, meta)
    return meta


def save_selection(
    session_id: str,
    *,
    selected_indices: list[int] | None = None,
    refine_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = load_meta(session_id)
    if selected_indices is not None:
        meta["selected_indices"] = sorted(set(selected_indices))
    if refine_options is not None:
        current = dict(meta.get("refine_options") or {})
        current.update(refine_options)
        meta["refine_options"] = current
    save_meta(session_id, meta)
    return meta


def save_last_results(session_id: str, results: list[dict[str, Any]]) -> None:
    update_meta(session_id, last_results=results)


def list_recent_sessions(limit: int = 20) -> list[dict[str, Any]]:
    base = _sessions_base()
    entries: list[tuple[float, str, Path]] = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / META_NAME
        if not meta_path.is_file():
            continue
        try:
            mtime = meta_path.stat().st_mtime
            entries.append((mtime, d.name, meta_path))
        except OSError:
            continue
    entries.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for _mtime, sid, meta_path in entries[:limit]:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "session_id": sid,
                "original_filename": meta.get("original_filename", "document.docx"),
                "selected_count": len(meta.get("selected_indices") or []),
                "eligible_count": len(meta.get("eligible_indices") or []),
                "has_results": bool(meta.get("last_results")),
            }
        )
    return out


def session_payload(session_id: str) -> dict[str, Any]:
    meta = load_meta(session_id)
    return {
        "session_id": session_id,
        "paragraphs": meta["paragraphs"],
        "eligible_indices": meta["eligible_indices"],
        "selected_indices": meta.get("selected_indices") or [],
        "refine_options": meta.get("refine_options") or {},
        "last_results": meta.get("last_results") or [],
        "original_filename": meta.get("original_filename", "document.docx"),
    }


def load_meta(session_id: str) -> dict[str, Any]:
    p = session_dir(session_id) / META_NAME
    if not p.is_file():
        raise FileNotFoundError("session not found")
    return json.loads(p.read_text(encoding="utf-8"))


def original_path(session_id: str) -> Path:
    p = session_dir(session_id) / "original.docx"
    if not p.is_file():
        raise FileNotFoundError("original missing")
    return p


def delete_session(session_id: str) -> None:
    d = session_dir(session_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
