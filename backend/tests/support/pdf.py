"""Read the text and page count of a ReportLab PDF in tests (module 16), without a PDF library:
page content streams are ASCII85- and/or Flate-encoded; strings are drawn with Tj."""

import base64
import re
import zlib

STREAM = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.S)
PAGE = re.compile(rb"/Type /Page(?!s)")


def _decode(raw: bytes) -> bytes:
    data = raw.strip()
    if data.endswith(b"~>"):
        data = base64.a85decode(data[:-2], adobe=False)
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data


def _unescape(match: re.Match[str]) -> str:
    code = match.group(1)
    return chr(int(code, 8)) if code[0] in "01234567" else code


def pdf_text(pdf: bytes) -> str:
    """Every drawn string, in order, joined by newlines (PDF escapes undone)."""
    strings: list[str] = []
    for match in STREAM.finditer(pdf):
        content = _decode(match.group(1)).decode("latin-1")
        for text in re.findall(r"\(((?:\\.|[^\\)])*)\)\s*Tj", content):
            strings.append(re.sub(r"\\([0-7]{1,3}|.)", _unescape, text))
    return "\n".join(strings)


def page_count(pdf: bytes) -> int:
    return len(PAGE.findall(pdf))


def is_complete_pdf(pdf: bytes) -> bool:
    return pdf.startswith(b"%PDF-") and b"%%EOF" in pdf[-1024:] and len(pdf) > 500
