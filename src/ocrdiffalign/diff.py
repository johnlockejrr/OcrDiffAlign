"""Character-level diffing and confusion counting.

The old scripts paired up ``difflib.ndiff`` output by inspection, which loses information:
``ndiff('ab', 'cde')`` yields ``['- a', '- b', '+ c', '+ d', '+ e']``, and the pairing logic
linked at most one removed character to one added character and reported the rest as bare
deletions and insertions. ``get_opcodes`` states the same relationship explicitly, so
replace groups can be paired positionally and the leftovers reported correctly.

Both sides are compared *normalised*. Comparing raw OCR against normalised reference text
counts every punctuation mark and stray Latin character as a Hebrew letter confusion, which
is what the previous implementation did.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from html import escape

_OCR_CLASS = "ocr-only"
_REF_CLASS = "ref-only"


@dataclass(frozen=True)
class Confusion:
    """One observed substitution. An empty side means the character was added or lost."""

    ocr_char: str
    ref_char: str
    count: int

    @property
    def label(self) -> str:
        return f"{self.ocr_char or '∅'} → {self.ref_char or '∅'}"


@dataclass(frozen=True)
class Diff:
    """Rendered diff plus the raw character pairs it was built from."""

    html: str
    pairs: tuple[tuple[str, str], ...]


def _span(css_class: str, char: str) -> str:
    return f'<span class="{css_class}">{escape(char)}</span>'


@lru_cache(maxsize=8192)
def char_diff(ocr: str, ref: str) -> Diff:
    """Diff two strings, returning HTML markup and the ``(ocr_char, ref_char)`` pairs.

    Output is escaped because the browser renders it as HTML; the old Streamlit app
    interpolated raw OCR text into ``unsafe_allow_html``, which made any ``<`` in the
    source injectable.
    """
    parts: list[str] = []
    pairs: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ocr, ref, autojunk=False).get_opcodes():
        if tag == "equal":
            parts.append(escape(ocr[i1:i2]))
        elif tag == "delete":
            for char in ocr[i1:i2]:
                parts.append(_span(_OCR_CLASS, char))
                if not char.isspace():
                    pairs.append((char, ""))
        elif tag == "insert":
            for char in ref[j1:j2]:
                parts.append(_span(_REF_CLASS, char))
                if not char.isspace():
                    pairs.append(("", char))
        else:  # replace: pair the characters positionally, report the surplus on its own
            ocr_side, ref_side = ocr[i1:i2], ref[j1:j2]
            shared = min(len(ocr_side), len(ref_side))
            for ocr_char, ref_char in zip(ocr_side[:shared], ref_side[:shared], strict=True):
                parts.append(_span(_OCR_CLASS, ocr_char) + _span(_REF_CLASS, ref_char))
                if not ocr_char.isspace() and not ref_char.isspace():
                    pairs.append((ocr_char, ref_char))
            for ocr_char in ocr_side[shared:]:
                parts.append(_span(_OCR_CLASS, ocr_char))
                if not ocr_char.isspace():
                    pairs.append((ocr_char, ""))
            for ref_char in ref_side[shared:]:
                parts.append(_span(_REF_CLASS, ref_char))
                if not ref_char.isspace():
                    pairs.append(("", ref_char))

    return Diff(html="".join(parts), pairs=tuple(pairs))


def count_confusions(pairs: Iterable[tuple[str, str]]) -> tuple[Confusion, ...]:
    """Aggregate ``(ocr_char, ref_char)`` pairs into ranked confusions."""
    collected = Counter(pairs)
    return tuple(
        Confusion(ocr_char, ref_char, count)
        for (ocr_char, ref_char), count in sorted(
            collected.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    )
