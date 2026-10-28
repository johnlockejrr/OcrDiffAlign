from __future__ import annotations

from pathlib import Path

import pytest

from ocrdiffalign.index import Match, ReferenceIndex, load_reference


@pytest.fixture
def index(mini_reference_text: str) -> ReferenceIndex:
    return ReferenceIndex.from_text(mini_reference_text, max_span=2)


def test_line_and_candidate_counts(mini_reference_text: str, index: ReferenceIndex) -> None:
    lines = mini_reference_text.splitlines()
    assert index.line_count == len(lines)
    # Five single-line candidates plus four two-line joins, all distinct.
    assert index.candidate_count == len(lines) + len(lines) - 1


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
def test_every_line_is_findable_with_its_own_number(
    mini_reference_text: str, index: ReferenceIndex, position: int
) -> None:
    line = mini_reference_text.splitlines()[position]
    match = index.best_global(line)
    assert match.text == line
    assert match.score == pytest.approx(100.0)
    assert match.ref_index == position + 1


def test_two_line_candidate_reports_the_line_it_starts_on(index: ReferenceIndex) -> None:
    joined = "ויאמר אלהים יהי מארת ויבדל בין המים"
    match = index.best_global(joined)
    assert match.text == joined
    assert match.ref_index == 2


def test_windowed_search_misses_a_distant_line(index: ReferenceIndex) -> None:
    query = "ולילוק קרא חשך"
    assert index.best_near(query, center=0, radius=1).ref_index != 5


def test_weak_window_falls_back_to_a_global_search(index: ReferenceIndex) -> None:
    query = "ולילוק קרא חשך"
    assert index.best_near(query, center=0, radius=1).score < 60
    assert index.match_for(query, anchor=0).ref_index == 5


def test_strong_window_is_not_re_searched_globally(index: ReferenceIndex) -> None:
    query = "ויאמר אלהים יהי מארת"
    assert index.match_for(query, anchor=1).ref_index == 2


def test_empty_query_never_matches(index: ReferenceIndex) -> None:
    assert index.match_for("", anchor=0) == Match.none()
    assert Match.none().ref_index == 0


def test_empty_index_yields_no_match() -> None:
    assert ReferenceIndex(()).best_global("ברא") == Match.none()


def test_duplicate_text_reports_the_first_occurrence() -> None:
    index = ReferenceIndex(["ברא", "ברא"], max_span=1)
    assert index.best_global("ברא").ref_index == 1


def test_loading_the_same_file_twice_reuses_one_index(tmp_path: Path) -> None:
    reference = tmp_path / "ref.txt"
    reference.write_text("ברא\nברא\n", encoding="utf-8")
    assert load_reference(reference) is load_reference(reference)
