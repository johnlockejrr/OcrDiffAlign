from __future__ import annotations

from pathlib import Path

import pytest

from ocrdiffalign.errors import FileTooLarge, InvalidInput
from ocrdiffalign.text import normalize, read_text, split_lines


def test_removes_latin_digits_and_punctuation() -> None:
    assert normalize("abc ברא123! ()") == "ברא"


def test_preserves_final_forms() -> None:
    """Unifying ן/נ would hide exactly the confusions this toolkit measures."""
    assert normalize("דבר אלהינו") == "דבר אלהינו"


def test_keeps_niqqud_and_maqqef() -> None:
    assert normalize("בְּרֵאשִׁ֖ית") == "בְּרֵאשִׁית"


def test_collapses_repeated_whitespace() -> None:
    assert normalize("ברא   ית\tברא") == "ברא ית ברא"


def test_strips_byte_order_mark() -> None:
    assert normalize("﻿ברא") == "ברא"


def test_normalize_is_idempotent() -> None:
    once = normalize("  ברא  שית  ")
    assert normalize(once) == once


def test_read_text_accepts_bom(tmp_path: Path) -> None:
    path = tmp_path / "ocr.txt"
    path.write_bytes("﻿ברא".encode("utf-8"))
    assert read_text(path, max_bytes=1024).endswith("ברא")


def test_read_text_rejects_non_utf8(tmp_path: Path) -> None:
    path = tmp_path / "ocr.txt"
    path.write_bytes(b"\xff\xfe\x00r\x00a")
    with pytest.raises(InvalidInput):
        read_text(path, max_bytes=1024)


def test_read_text_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "ocr.txt"
    path.write_text("ברא", encoding="utf-8")
    with pytest.raises(FileTooLarge):
        read_text(path, max_bytes=1)


def test_read_text_of_missing_file_raises() -> None:
    with pytest.raises(InvalidInput):
        read_text(Path("/nonexistent/ocr.txt"), max_bytes=1024)


def test_split_lines_drops_blanks_and_normalise_line_endings() -> None:
    content = "ברא\r\n\r\n  ברא  \n\x0c\n"
    assert split_lines(content) == ["ברא", "ברא"]
