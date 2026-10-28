from __future__ import annotations

from pathlib import Path

import pytest

from ocrdiffalign.align import (
    LineResult,
    align_lines,
    align_reference_text,
    align_text,
    format_report,
    render_confusions_csv,
    render_csv,
    render_matched_text,
    summarize,
    write_atomic,
)
from ocrdiffalign.index import ReferenceIndex
from ocrdiffalign.text import split_lines


def test_reference_lines_align_to_themselves_in_order(mini_reference_text: str) -> None:
    alignment = align_reference_text(mini_reference_text, mini_reference_text)
    assert [result.ref_index for result in alignment.results] == [1, 2, 3, 4, 5]
    assert all(result.score == pytest.approx(100.0) for result in alignment.results)
    assert alignment.confusions == ()


def test_substituted_line_is_matched_and_logged(mini_reference_text: str) -> None:
    ocr = "ברתשית ברא האלהים את השמים"
    alignment = align_reference_text(ocr, mini_reference_text)
    assert alignment.results[0].ref_index == 1
    assert ("ת", "א", 1) in [(c.ocr_char, c.ref_char, c.count) for c in alignment.confusions]


def test_line_without_hebrew_is_reported_but_not_matched(mini_reference_text: str) -> None:
    alignment = align_reference_text("17b", mini_reference_text)
    result = alignment.results[0]
    assert (result.line_no, result.ocr, result.normalized) == (1, "17b", "")
    assert result.score == 0.0 and result.ref_index == 0 and result.diff_html == ""


def test_sample_ocr_file_aligns_against_the_reference(ocr_sample: str, ref_path: Path) -> None:
    alignment = align_text(ocr_sample, ref_path)
    assert alignment.summary.lines == len(split_lines(ocr_sample))
    assert all(result.match for result in alignment.results)
    assert alignment.summary.average_score > 60


def test_scores_below_threshold_are_counted_as_low(mini_reference_text: str) -> None:
    alignment = align_reference_text(mini_reference_text, mini_reference_text, threshold=99)
    assert alignment.summary.low_count == 0  # perfect matches are not "low"
    assert alignment.summary.threshold == 99


def test_csv_has_headers_and_one_row_per_line(mini_reference_text: str) -> None:
    alignment = align_reference_text(mini_reference_text, mini_reference_text)
    rows = render_csv(alignment.results).splitlines()
    assert rows[0] == (
        "Line No,OCR Line,Normalized OCR,Reference Line No,Reference Line,Score,Final Match"
    )
    assert len(rows) == len(alignment.results) + 1
    assert rows[1].startswith("1,בראשית ברא האלהים את השמים,")


def test_matched_text_holds_one_final_match_per_line(mini_reference_text: str) -> None:
    alignment = align_reference_text(mini_reference_text, mini_reference_text)
    assert render_matched_text(alignment.results).splitlines() == mini_reference_text.splitlines()


def test_confusions_csv_lists_counts(mini_reference_text: str) -> None:
    alignment = align_reference_text("ברתשית ברא האלהים את השמים", mini_reference_text)
    rendered = render_confusions_csv(alignment.confusions)
    assert rendered.splitlines()[0] == "Confused Char,Confused With,Count"
    assert "ת,א,1" in rendered


def test_format_report_lists_totals_and_top_confusions(mini_reference_text: str) -> None:
    report = format_report(align_reference_text("ברתשית ברא האלהים את השמים", mini_reference_text))
    assert "Lines processed: 1" in report
    assert "Average score:" in report
    assert "ת → א : 1 times" in report


def test_save_writes_all_three_artefacts_without_temp_leftovers(
    tmp_path: Path, mini_reference_text: str
) -> None:
    alignment = align_reference_text(mini_reference_text, mini_reference_text)
    paths = alignment.save(tmp_path / "aligned", stem="run")

    assert paths["csv"].read_text(encoding="utf-8") == alignment.csv()
    assert paths["txt"].read_text(encoding="utf-8") == alignment.matched_text()
    assert paths["confusions_csv"].read_text(encoding="utf-8") == alignment.confusions_csv()
    assert sorted(p.name for p in (tmp_path / "aligned").iterdir()) == [
        "confusions_run.csv",
        "run.csv",
        "run.txt",
    ]


def test_write_atomic_replaces_content(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    write_atomic(target, "first")
    write_atomic(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    assert list(tmp_path.iterdir()) == [target]


def test_summary_math_is_exact() -> None:
    results = [
        LineResult(1, "א", "א", "א", 100.0, 1, "א", ""),
        LineResult(2, "ב", "ב", "ב", 50.0, 2, "ב", ""),
    ]
    summary = summarize(results, threshold=70)
    assert (summary.lines, summary.average_score, summary.low_count, summary.low_pct) == (
        2,
        75.0,
        1,
        50.0,
    )


def test_align_lines_against_an_explicit_index(mini_reference_text: str) -> None:
    index = ReferenceIndex(split_lines(mini_reference_text), max_span=2)
    assert align_lines(["ויבדל בין המים"], index).results[0].ref_index == 3
