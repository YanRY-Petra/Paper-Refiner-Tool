"""Insert paragraph text into prompts without using str.format (avoids braces in thesis)."""

from __future__ import annotations

_PLACEHOLDER = "{text}"


def inject_paragraph_text(template: str, paragraph_text: str) -> str:
    """
    Replace the single literal ``{text}`` placeholder in ``template``.

    Using :meth:`str.format` is unsafe: thesis paragraphs may contain ``{`` / ``}``
    (e.g. citations, code), which breaks formatting and caused 500 errors in the web UI.
    """
    if _PLACEHOLDER not in template:
        raise ValueError(f"Prompt template must contain {_PLACEHOLDER!r}.")
    first = template.find(_PLACEHOLDER)
    second = template.find(_PLACEHOLDER, first + len(_PLACEHOLDER))
    if second != -1:
        raise ValueError(f"Prompt template must contain {_PLACEHOLDER!r} exactly once.")
    before = template[:first]
    after = template[first + len(_PLACEHOLDER) :]
    return before + paragraph_text + after
