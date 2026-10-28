"""Reference index and candidate lookup.

A manuscript page does not break lines where a printed edition does: one OCR line can be half a
reference verse, a whole one, or one and a half. The answer to "what is the best match?" is
therefore a *span of words*, not a line — ``final_match`` replaces the OCR line, so a match
longer than the line it replaces is a wrong answer however high its score. The candidate set is
what ``align.py`` called ``build_windows``: for a query of ``n`` words, every ``n-1``, ``n`` and
``n+1`` word span of the reference.

Two further fixes over the earlier implementations:

* ``align.py`` rebuilt those windows for every OCR line and then re-derived the position with
  ``reference.find(match)``, which reports the first copy for repeated text and costs a scan per
  line. Every span here carries the reference line it starts on, so nothing is searched for.
* ``align-pagexml-index.py`` pre-built spans of 1..20 words (~1.6M strings for an 82k-word
  reference) and rebuilt them for *each* input file. Only the lengths an OCR line actually asks
  for are built, a line with a known neighbour reads a handful of reference lines, and the full
  set is built once per length and reused. One index per reference replaces one per document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from .config import DEFAULT_MAX_UPLOAD_BYTES
from .errors import FileTooLarge
from .text import read_text, split_lines

DEFAULT_MAX_EXTRA_WORDS = 1
DEFAULT_LINE_RADIUS = 3
SEARCH_SCORE_FLOOR = 60.0
MAX_CACHED_SPAN_SETS = 4
NO_MATCH = 0


@dataclass(frozen=True)
class Match:
    """Best span found for one query line; ``line_index`` is 0-based, -1 when nothing matched."""

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
    """Word spans of a reference text, each tagged with the line it starts on."""

    def __init__(
        self, lines: Sequence[str], max_extra_words: int = DEFAULT_MAX_EXTRA_WORDS
    ) -> None:
        self.lines: tuple[str, ...] = tuple(lines)
        self._extra = max(0, max_extra_words)

        words: list[str] = []
        starts: list[int] = []
        counts: list[int] = []
        for line in self.lines:
            line_words = line.split()
            starts.append(len(words))
            counts.append(len(line_words))
            words.extend(line_words)
        self._words: tuple[str, ...] = tuple(words)
        self._starts: tuple[int, ...] = tuple(starts)
        self._counts: tuple[int, ...] = tuple(counts)
        self._spans: dict[tuple[int, ...], tuple[tuple[str, ...], tuple[int, ...]]] = {}

    @classmethod
    def from_text(cls, text: str, max_extra_words: int = DEFAULT_MAX_EXTRA_WORDS) -> ReferenceIndex:
        return cls(split_lines(text), max_extra_words)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def word_count(self) -> int:
        return len(self._words)

    def _lengths_for(self, query: str) -> tuple[int, ...]:
        """Word counts to offer: the query's own plus ``max_extra_words`` on each side."""
        base = len(query.split())
        return tuple(w for w in range(base - self._extra, base + self._extra + 1) if w > 0)

    def _build_spans(
        self, lengths: tuple[int, ...], lines: range
    ) -> tuple[tuple[str, ...], tuple[int, ...]]:
        """Every span of those lengths starting on a word of ``lines``, in reference order.

        ``dict`` keeps the first entry per string, so a span that also occurs later in the
        reference still reports the earliest line it was read from.
        """
        found: dict[str, int] = {}
        limit = len(self._words)
        for line in lines:
            offset, available = self._starts[line], self._counts[line]
            for length in lengths:
                for start in range(offset, offset + available):
                    if start + length <= limit:
                        found.setdefault(" ".join(self._words[start : start + length]), line)
        return tuple(found), tuple(found.values())

    def _cached_spans(self, lengths: tuple[int, ...]) -> tuple[tuple[str, ...], tuple[int, ...]]:
        """Spans of ``lengths`` over the whole reference, built once per length set."""
        cached = self._spans.get(lengths)
        if cached is None:
            built = self._build_spans(lengths, range(len(self.lines)))
            if len(self._spans) >= MAX_CACHED_SPAN_SETS:
                self._spans.pop(next(iter(self._spans)))
            self._spans[lengths] = built
            cached = built
        return cached

    @staticmethod
    def _best_of(query: str, candidates: tuple[tuple[str, ...], tuple[int, ...]]) -> Match:
        texts, owners = candidates
        if not texts:
            return Match.none()
        # rapidfuzz always yields ``(choice, score, index)`` and ``index`` is the position in
        # ``texts``; that is what makes the owning line known without a string search.
        choice, score, index = process.extract(query, list(texts), scorer=fuzz.ratio, limit=1)[0]
        return Match(choice, float(score), owners[index])

    def best_global(self, query: str) -> Match:
        """Best span anywhere in the reference."""
        lengths = self._lengths_for(query) if query else ()
        if not lengths:
            return Match.none()
        return self._best_of(query, self._cached_spans(lengths))

    def best_near(self, query: str, center: int, radius: int = DEFAULT_LINE_RADIUS) -> Match:
        """Best span within the reference lines ``[center-radius, center+radius]``."""
        lengths = self._lengths_for(query) if query else ()
        if not lengths or not self.lines:
            return Match.none()
        low, high = max(0, center - radius), min(len(self.lines), center + radius + 1)
        return self._best_of(query, self._build_spans(lengths, range(low, high)))

    def match_for(self, query: str, anchor: int = -1, radius: int = DEFAULT_LINE_RADIUS) -> Match:
        """Match one OCR line, trusting the neighbourhood of ``anchor`` before searching wider.

        OCR runs in reference order, so the line before this one says where to look. A weak score
        there means the anchor is wrong (a skipped line, a page boundary), so the whole reference
        is consulted and the better of the two wins.
        """
        if not query or not self._words:
            return Match.none()
        if anchor < 0:
            return self.best_global(query)
        near = self.best_near(query, anchor, radius)
        if near.score >= SEARCH_SCORE_FLOOR:
            return near
        wide = self.best_global(query)
        return wide if wide.score > near.score else near


@lru_cache(maxsize=4)
def _build(
    path_str: str,
    mtime_ns: int,
    size: int,
    max_extra_words: int,
    max_bytes: int,
) -> ReferenceIndex:
    if size > max_bytes:
        raise FileTooLarge(f"{Path(path_str).name} is {size} bytes, limit is {max_bytes} bytes.")
    return ReferenceIndex.from_text(read_text(Path(path_str), max_bytes=max_bytes), max_extra_words)


def load_reference(
    path: Path,
    *,
    max_extra_words: int = DEFAULT_MAX_EXTRA_WORDS,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> ReferenceIndex:
    """Load and index a reference file, reusing the index while the file is unchanged.

    The old optimised script rebuilt the index once per input document; caching on
    ``(path, mtime, size)`` builds it once per reference for the life of the process.
    """
    stat = Path(path).stat()
    return _build(str(path), stat.st_mtime_ns, stat.st_size, max_extra_words, max_bytes)


__all__ = [
    "DEFAULT_LINE_RADIUS",
    "DEFAULT_MAX_EXTRA_WORDS",
    "Match",
    "ReferenceIndex",
    "load_reference",
]
