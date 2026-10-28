"""Text loading and normalisation.

Normalisation keeps Hebrew code points and whitespace and drops everything else, which is
what the original scripts did. Final forms are preserved on purpose: unifying ``ן``/``נ``
hides exactly the confusions the toolkit is trying to measure.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import FileTooLarge, InvalidInput

# Hebrew block: letters, niqqud, te'amim and presentation forms.
_NON_HEBREW = re.compile(r"[^֐-׿\s]")
_WHITESPACE = re.compile(r"\s+")
_BOM = "﻿"


def normalize(text: str) -> str:
    """Strip everything but Hebrew characters and collapse whitespace to single spaces."""
    without_bom = text.lstrip(_BOM)
    without_other = _NON_HEBREW.sub("", without_bom)
    return _WHITESPACE.sub(" ", without_other).strip()


def read_text(path: Path, *, max_bytes: int) -> str:
    """Read a UTF-8 (optionally BOM-prefixed) text file, refusing oversized files."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InvalidInput(f"Cannot read {path}: {exc}") from exc
    if size > max_bytes:
        raise FileTooLarge(f"{path.name} is {size} bytes, limit is {max_bytes} bytes.")
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput(f"{path.name} is not valid UTF-8: {exc}") from exc


def split_lines(content: str) -> list[str]:
    """Split OCR content into non-empty lines, tolerating CRLF and form feeds."""
    lines: list[str] = []
    for raw in content.splitlines():
        stripped = raw.strip().strip("\x0b\x0c\r")
        if stripped:
            lines.append(stripped)
    return lines
