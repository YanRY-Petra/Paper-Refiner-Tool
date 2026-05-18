"""WordprocessingML / Drawing / Math helpers."""

from __future__ import annotations

from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def paragraph_in_table(paragraph) -> bool:
    el = paragraph._element
    while el is not None:
        if el.tag == qn("w:tbl"):
            return True
        el = el.getparent()
    return False


def paragraph_has_drawing_or_picture(paragraph) -> bool:
    root = paragraph._element
    if root.findall(".//" + qn("w:drawing")):
        return True
    if root.findall(".//" + qn("w:pict")):
        return True
    return False


def paragraph_has_math(paragraph) -> bool:
    root = paragraph._element
    if root.findall(".//" + qn("m:oMath")):
        return True
    if root.findall(".//" + qn("m:oMathPara")):
        return True
    return False


def paragraph_has_complex_fields(paragraph) -> bool:
    """Hyperlinks, footnote refs, comments — conservative skip for v1."""
    root = paragraph._element
    if root.findall(".//" + qn("w:hyperlink")):
        return True
    if root.findall(".//" + qn("w:footnoteReference")):
        return True
    if root.findall(".//" + qn("w:endnoteReference")):
        return True
    if root.findall(".//" + qn("w:commentReference")):
        return True
    return False
