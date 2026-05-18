"""Write rewritten plain text back into a paragraph (best-effort)."""

from __future__ import annotations


def replace_paragraph_plain_text(paragraph, new_text: str) -> None:
    """
    Replace visible text with `new_text`, collapsing runs into the first run.

    Preserves ``w:pPr`` (indents, spacing, alignment). Intra-paragraph mixed
    formatting (bold in the middle of a sentence) may be flattened — see README.
    """
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(new_text)
        return
    runs[0].text = new_text
    for run in runs[1:]:
        el = run._element
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
