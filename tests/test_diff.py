from __future__ import annotations

from ocrdiffalign.diff import char_diff, count_confusions


def test_identical_strings_produce_no_confusions() -> None:
    diff = char_diff("בראשית", "בראשית")
    assert diff.pairs == ()
    assert diff.html == "בראשית"


def test_single_substitution_is_reported_as_a_pair() -> None:
    diff = char_diff("בראשית", "ברתשית")
    assert diff.pairs == (("א", "ת"),)
    assert diff.html == (
        'בר<span class="ocr-only">א</span><span class="ref-only">ת</span>שית'
    )


def test_multi_character_replace_is_paired_positionally() -> None:
    """``ndiff('ab','cde')`` yields ``['- a','- b','+ c','+ d','+ e']``.

    The previous implementation paired only ``b``→``c`` and reported ``a`` as a bare deletion
    plus ``d`` and ``e`` as bare insertions.
    """
    assert set(char_diff("ab", "cde").pairs) == {("a", "c"), ("b", "d"), ("", "e")}


def test_pure_insertion_and_deletion_are_distinguished() -> None:
    assert char_diff("ברא", "בר").pairs == (("א", ""),)
    assert char_diff("בר", "ברא").pairs == (("", "א"),)


def test_whitespace_changes_are_not_counted_as_letter_confusions() -> None:
    """A space is marked up but not logged, since it is not a letter confusion."""
    assert char_diff("ברא ברא", "ברא").pairs == (("ב", ""), ("ר", ""), ("א", ""))


def test_confusion_counts_are_aggregated_and_ranked() -> None:
    pairs = [("ת", "ש"), ("ת", "ש"), ("ל", ""), ("", "ו")]
    confusions = count_confusions(pairs)
    assert [(c.ocr_char, c.ref_char, c.count) for c in confusions] == [
        ("ת", "ש", 2),
        ("", "ו", 1),
        ("ל", "", 1),
    ]


def test_empty_side_is_rendered_as_the_empty_set() -> None:
    confusions = count_confusions([("ל", "")])
    assert confusions[0].label == "ל → ∅"


def test_markup_is_escaped_so_ocr_content_cannot_inject_html() -> None:
    """The old app interpolated raw OCR text into ``unsafe_allow_html``."""
    diff = char_diff("<b>", "<i>")
    assert "&lt;" in diff.html and "&gt;" in diff.html
    assert "<b>" not in diff.html and "<i>" not in diff.html


def test_repeated_calls_return_the_cached_result() -> None:
    assert char_diff("ברא", "בר") is char_diff("ברא", "בר")
