"""Reference index and candidate lookup.

Two problems in the earlier implementations are fixed here.

``align.py`` rebuilt word windows per line and then re-derived the position with
``reference.find(match)``, throwing away the index rapidfuzz had already returned — for
repeated text that reports the wrong location. Here every candidate carries the reference
line it came from, so no searching is needed.

``align-pagexml-index.py`` pre-built every window from 1 to 20 words (~1.6M strings for an
82k-word reference) and rebuilt them for *each* input file, which is not identical to the
windowed behaviour it claimed to reproduce. Because OCR lines follow the reference in order,
this index instead searches a moving window around the previous match, and falls back to a
global search only when that window scores badly. Cheaper, and it stops a line on page two
matching a verse on page forty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import process

from .config import DEFAULT_MAX_UPLOAD_BYTES
from .errors import FileTooLarge
from .text import read_text, split_lines

DEFAULT_MAX_SPAN = 2
DEFAULT_WINDOW_RADIUS = 25
WINDOW_SCORE_FLOOR = 60.0
NO_MATCH = 0


@dataclass(frozen=True)
class Match:
    """Best candidate for one query line; ``line_index`` is 0-based, -1 when nothing matched."""

    text: str
    score: float
    line_index: int

    @property
    def ref_index(self) -> int:
        """1-based reference line number; ``0`` means no match was found."""
        return self.line_index + 1 if self.line_index >= 0 else NO_MATCH

    @classmethod
    def none(cls) -> Match:
        return cls("", 0.0, -1)


class ReferenceIndex:
    """Candidate strings derived from reference lines, each tagged with its source line."""

    def __init__(self, lines: Sequence[str], max_span: int = DEFAULT_MAX_SPAN) -> None:
        self.lines: tuple[str, ...] = tuple(lines)
        texts: list[str] = []
        owners: list[int] = []
        groups: list[tuple[int, ...]] = []
        seen: dict[str, int] = {}

        for index, _line in enumerate(self.lines):
            positions: list[int] = []
            for span in range(1, max_span + 1):
                if index + span > len(self.lines):
                    break
                text = " ".join(self.lines[index : index + span])
                position = seen.get(text)
                if position is None:
                    position = len(texts)
                    seen[text] = position
                    texts.append(text)
                    owners.append(index)
                positions.append(position)
            groups.append(tuple(positions))

        self._texts: tuple[str, ...] = tuple(texts)
        self._owners: tuple[int, ...] = tuple(owners)
        self._groups: tuple[tuple[int, ...], ...] = tuple(groups)

    @classmethod
    def from_text(cls, text: str, max_span: int = DEFAULT_MAX_SPAN) -> ReferenceIndex:
        return cls(split_lines(text), max_span)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def candidate_count(self) -> int:
        return len(self._texts)

    def window(self, center: int, radius: int) -> tuple[tuple[str, ...], tuple[int, ...]]:
        """Candidates sourced from reference lines ``[center-radius, center+radius]``."""
        if not self._groups:
            return (), ()
        low = max(0, center - radius)
        high = min(len(self._groups), center + radius + 1)
        positions = [p for group in self._groups[low:high] for p in group]
        return (
            tuple(self._texts[p] for p in positions),
            tuple(self._owners[p] for p in positions),
        )

    def _best_of(self, query: str, texts: tuple[str, ...], owners: tuple[int, ...]) -> Match:
        if not texts:
            return Match.none()
        # rapidfuzz always yields ``(choice, score, index)``; ``index`` is the position in
        # ``texts``, which is what makes the reference line knowable without a string search.
        choice, score, index = process.extract(query, list(texts), limit=1)[0]
        return Match(choice, float(score), owners[index])

    def best_global(self, query: str) -> Match:
        return self._best_of(query, self._texts, self._owners)

    def best_near(self, query: str, center: int, radius: int = DEFAULT_WINDOW_RADIUS) -> Match:
        texts, owners = self.window(center, radius)
        return self._best_of(query, texts, owners)

    def match_for(self, query: str, anchor: int = -1, radius: int = DEFAULT_WINDOW_RADIUS) -> Match:
        """Match one query line, preferring candidates near ``anchor`` and widening if weak."""
        if not query or not self._texts:
            return Match.none()
        if anchor >= 0:
            near = self.best_near(query, anchor, radius)
            if near.score >= WINDOW_SCORE_FLOOR:
                return near
        return self.best_global(query)


@lru_cache(maxsize=4)
def _build(
    path_str: str,
    mtime_ns: int,
    size: int,
    max_span: int,
    max_bytes: int,
) -> ReferenceIndex:
    if size > max_bytes:
        raise FileTooLarge(f"{Path(path_str).name} is {size} bytes, limit is {max_bytes} bytes.")
    return ReferenceIndex.from_text(read_text(Path(path_str), max_bytes=max_bytes), max_span)


def load_reference(
    path: Path,
    *,
    max_span: int = DEFAULT_MAX_SPAN,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> ReferenceIndex:
    """Load and index a reference file, reusing the index while the file is unchanged.

    The old optimised script rebuilt the index once per input document; caching on
    ``(path, mtime, size)`` builds it once per reference for the life of the process.
    """
    stat = Path(path).stat()
    return _build(str(path), stat.st_mtime_ns, stat.st_size, max_span, max_bytes)
