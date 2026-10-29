"""Alignment of OCR lines against a reference, and the artefacts it produces."""

from __future__ import annotations

import csv
import io
import os
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .diff import Confusion, Diff, char_diff, count_confusions
from .index import (
    DEFAULT_LINE_RADIUS,
    DEFAULT_MAX_EXTRA_WORDS,
    Match,
    ReferenceIndex,
    load_reference,
)
from .text import normalize, read_text, split_lines


@dataclass(frozen=True)
class LineResult:
    """One OCR line, its match, and everything needed to review or export it."""

    line_no: int
    ocr: str
    normalized: str
    match: str
    score: float
    ref_index: int
    final_match: str
    diff_html: str


@dataclass(frozen=True)
class Summary:
    lines: int
    average_score: float
    threshold: int
    low_count: int
    low_pct: float


@dataclass(frozen=True)
class Alignment:
    """A full alignment run."""

    results: tuple[LineResult, ...]
    summary: Summary
    confusions: tuple[Confusion, ...]

    def csv(self) -> str:
        return render_csv(self.results)

    def matched_text(self) -> str:
        return render_matched_text(self.results)

    def confusions_csv(self) -> str:
        return render_confusions_csv(self.confusions)

    def save(self, output_dir: Path, stem: str | None = None) -> dict[str, Path]:
        """Write the three artefacts under ``output_dir`` and return their paths."""
        prefix = stem or f"alignment_{uuid.uuid4().hex[:8]}"
        return {
            "csv": write_atomic(Path(output_dir) / f"{prefix}.csv", self.csv()),
            "txt": write_atomic(Path(output_dir) / f"{prefix}.txt", self.matched_text()),
            "confusions_csv": write_atomic(
                Path(output_dir) / f"confusions_{prefix}.csv", self.confusions_csv()
            ),
        }


def render_csv(results: Sequence[LineResult]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "Line No",
            "OCR Line",
            "Normalized OCR",
            "Reference Line No",
            "Best Match",
            "Score",
            "Final Match",
        ]
    )
    for result in results:
        writer.writerow(
            [
                result.line_no,
                result.ocr,
                result.normalized,
                result.ref_index,
                result.match,
                f"{result.score:.2f}",
                result.final_match,
            ]
        )
    return buffer.getvalue()


def render_matched_text(results: Sequence[LineResult]) -> str:
    return "".join(f"{result.final_match}\n" for result in results)


def render_confusions_csv(confusions: Sequence[Confusion]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Confused Char", "Confused With", "Count"])
    for confusion in confusions:
        writer.writerow([confusion.ocr_char, confusion.ref_char, confusion.count])
    return buffer.getvalue()


def write_atomic(path: Path, content: str | bytes) -> Path:
    """Write a file by replacing a temporary sibling, so an interrupted run leaves no half-file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        if isinstance(content, bytes):
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
        else:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def summarize(results: Sequence[LineResult], threshold: int) -> Summary:
    scores = [result.score for result in results]
    average = round(sum(scores) / len(scores), 2) if scores else 0.0
    low_count = sum(1 for score in scores if score < threshold)
    low_pct = round(low_count / len(scores) * 100, 1) if scores else 0.0
    return Summary(len(results), average, threshold, low_count, low_pct)


def align_lines(
    lines: Sequence[str],
    index: ReferenceIndex,
    *,
    threshold: int = 70,
    radius: int = DEFAULT_LINE_RADIUS,
) -> Alignment:
    """Align already-split OCR lines against an index. Used by both the text and PAGE-XML paths."""
    results: list[LineResult] = []
    pairs: list[tuple[str, str]] = []
    anchor = -1

    for line_no, raw in enumerate(lines, 1):
        normalized = normalize(raw)
        if not normalized:
            results.append(LineResult(line_no, raw, "", "", 0.0, 0, "", ""))
            continue
        match = index.match_for(normalized, anchor, radius)
        rendered: Diff = char_diff(normalized, match.text)
        pairs.extend(rendered.pairs)
        results.append(
            LineResult(
                line_no=line_no,
                ocr=raw,
                normalized=normalized,
                match=match.text,
                score=round(match.score, 2),
                ref_index=match.ref_index,
                final_match=match.text,
                diff_html=rendered.html,
            )
        )
        if match.line_index >= 0:
            anchor = match.line_index

    return Alignment(
        results=tuple(results),
        summary=summarize(results, threshold),
        confusions=count_confusions(pairs),
    )


def align_text(
    ocr_content: str,
    reference_path: Path,
    *,
    threshold: int = 70,
    radius: int = DEFAULT_LINE_RADIUS,
) -> Alignment:
    """Align raw OCR content against a reference file."""
    return align_lines(
        split_lines(ocr_content),
        load_reference(reference_path),
        threshold=threshold,
        radius=radius,
    )


def align_reference_text(
    ocr_content: str,
    reference_text: str,
    *,
    threshold: int = 70,
    max_extra_words: int = DEFAULT_MAX_EXTRA_WORDS,
    radius: int = DEFAULT_LINE_RADIUS,
) -> Alignment:
    """Align against reference content given directly, bypassing the file cache."""
    return align_lines(
        split_lines(ocr_content),
        ReferenceIndex(split_lines(reference_text), max_extra_words),
        threshold=threshold,
        radius=radius,
    )


def format_report(alignment: Alignment) -> str:
    """CLI report: totals, average score, low-confidence lines and the top confusions."""
    summary = alignment.summary
    lines = [
        "📊 Summary Report",
        f"- Lines processed: {summary.lines}",
        f"- Average score: {summary.average_score:.2f}",
        f"- Low-confidence (<{summary.threshold}): {summary.low_count} lines "
        f"({summary.low_pct:.1f}%)",
    ]
    if alignment.confusions:
        lines.append("")
        lines.append("🔝 Top 5 Confusions:")
        for confusion in alignment.confusions[:5]:
            lines.append(f"  {confusion.label} : {confusion.count} times")
    return "\n".join(lines)


__all__ = [
    "Alignment",
    "LineResult",
    "Match",
    "Summary",
    "align_lines",
    "align_reference_text",
    "align_text",
    "format_report",
    "read_text",
    "render_confusions_csv",
    "render_csv",
    "render_matched_text",
    "summarize",
    "write_atomic",
]
