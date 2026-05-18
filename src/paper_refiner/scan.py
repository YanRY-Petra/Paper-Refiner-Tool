from __future__ import annotations

from dataclasses import dataclass

from docx import Document

from paper_refiner.xmlutil import (
    paragraph_has_complex_fields,
    paragraph_has_drawing_or_picture,
    paragraph_has_math,
    paragraph_in_table,
)


@dataclass
class ParagraphInfo:
    index: int
    style: str
    in_table: bool
    skip_reason: str | None
    preview: str
    full_text: str


def _preview(text: str, limit: int = 80) -> str:
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _style_name(paragraph) -> str:
    try:
        return paragraph.style.name if paragraph.style else ""
    except (AttributeError, KeyError):
        return ""


def _should_skip_by_style(style: str, cfg: dict) -> str | None:
    s = (style or "").lower()
    for frag in cfg.get("skip_style_substrings", []):
        if frag and frag.lower() in s:
            return f"style:{frag}"
    body_frags = cfg.get("body_style_substrings") or []
    if body_frags:
        ok = any(frag and frag.lower() in s for frag in body_frags)
        if not ok:
            return "style:not-in-body-allowlist"
    return None


def _structural_skip(paragraph) -> str | None:
    if paragraph_in_table(paragraph):
        return "table"
    if paragraph_has_drawing_or_picture(paragraph):
        return "image/drawing"
    if paragraph_has_math(paragraph):
        return "formula/math"
    if paragraph_has_complex_fields(paragraph):
        return "hyperlink/footnote/comment"
    text = (paragraph.text or "").strip()
    if not text:
        return "empty"
    return None


def scan_document(doc_path: str, filter_cfg: dict) -> list[ParagraphInfo]:
    doc = Document(doc_path)
    infos: list[ParagraphInfo] = []
    for i, p in enumerate(doc.paragraphs):
        style = _style_name(p)
        st = _structural_skip(p)
        if st:
            skip = st
        else:
            skip = _should_skip_by_style(style, filter_cfg)
        text = p.text or ""
        infos.append(
            ParagraphInfo(
                index=i,
                style=style,
                in_table=paragraph_in_table(p),
                skip_reason=skip,
                preview=_preview(text),
                full_text=text,
            )
        )
    return infos


def eligible_indices(infos: list[ParagraphInfo]) -> list[int]:
    return [x.index for x in infos if x.skip_reason is None]
