from __future__ import annotations

from pathlib import Path

import pytest

from ocrdiffalign.index import SEARCH_SCORE_FLOOR, Match, ReferenceIndex, load_reference


@pytest.fixture
def index(mini_reference_text: str) -> ReferenceIndex:
    return ReferenceIndex.from_text(mini_reference_text)


def test_line_and_word_counts(mini_reference_text: str, index: ReferenceIndex) -> None:
    lines = mini_reference_text.splitlines()
    assert index.line_count == len(lines)
    assert index.word_count == sum(len(line.split()) for line in lines)


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
def test_every_line_is_findable_with_its_own_number(
    mini_reference_text: str, index: ReferenceIndex, position: int
) -> None:
    line = mini_reference_text.splitlines()[position]
    match = index.best_global(line)
    assert match.text == line
    assert match.score == pytest.approx(100.0)
    assert match.ref_index == position + 1


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
def test_a_fragment_of_a_line_matches_that_fragment_and_nothing_more(
    mini_reference_text: str, index: ReferenceIndex, position: int
) -> None:
    """The reported failure: a short OCR line used to answer with the whole surrounding line."""
    first_two = " ".join(mini_reference_text.splitlines()[position].split()[:2])
    match = index.best_global(first_two)
    assert match.text.split() == first_two.split()
    assert match.score == pytest.approx(100.0)
    assert match.ref_index == position + 1


def test_a_span_crossing_two_lines_reports_the_line_it_starts_on(index: ReferenceIndex) -> None:
    joined = "ויאמר אלהים יהי מארת ויבדל בין המים"
    match = index.best_global(joined)
    assert match.text == joined
    assert match.ref_index == 2


def test_spans_stop_at_one_word_more_than_the_query(index: ReferenceIndex) -> None:
    narrow = ReferenceIndex(["בראשית ברא האלהים"], max_extra_words=0)
    assert narrow.best_global("בראשית ברא").text == "בראשית ברא"
    assert narrow.best_global("בראשית ברא").ref_index == 1


def test_a_distant_line_is_out_of_reach_of_a_narrow_neighbourhood(index: ReferenceIndex) -> None:
    query = "ולילוק קרא חשך"
    near = index.best_near(query, center=0, radius=1)
    assert near.score < SEARCH_SCORE_FLOOR
    assert near.ref_index != 5


def test_a_weak_neighbourhood_falls_back_to_the_whole_reference(index: ReferenceIndex) -> None:
    query = "ולילוק קרא חשך"
    assert index.match_for(query, anchor=0, radius=1).ref_index == 5


def test_a_strong_neighbourhood_is_not_searched_globally(index: ReferenceIndex) -> None:
    query = "ויאמר אלהים יהי מארת"
    assert index.match_for(query, anchor=1).ref_index == 2


def test_empty_query_never_matches(index: ReferenceIndex) -> None:
    assert index.match_for("", anchor=0) == Match.none()
    assert Match.none().ref_index == 0


def test_empty_index_yields_no_match() -> None:
    assert ReferenceIndex(()).best_global("ברא") == Match.none()


def test_duplicate_text_reports_the_first_occurrence() -> None:
    assert ReferenceIndex(["ברא", "ברא"]).best_global("ברא").ref_index == 1


def test_loading_the_same_file_twice_reuses_one_index(tmp_path: Path) -> None:
    reference = tmp_path / "ref.txt"
    reference.write_text("ברא\nברא\n", encoding="utf-8")
    assert load_reference(reference) is load_reference(reference)
