from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from ocrdiffalign.align import Alignment, LineResult, align_lines, summarize
from ocrdiffalign.errors import FileTooLarge, InvalidDocument, InvalidInput
from ocrdiffalign.index import ReferenceIndex
from ocrdiffalign.pagexml import (
    PAGE_SCHEMA_PREFIX,
    DocumentFailure,
    DocumentOutcome,
    align_document,
    align_documents,
    apply_alignment,
    detect_namespace,
    parse_bytes,
    serialize,
)
from ocrdiffalign.text import split_lines

PAGE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"


def page_bytes(*texts: str) -> bytes:
    """A minimal PAGE-XML document whose TextLines hold exactly ``texts``."""
    lines = "".join(
        f'<TextLine id="l{number}"><TextEquiv>'
        f"<Unicode>{text}</Unicode></TextEquiv></TextLine>"
        for number, text in enumerate(texts, start=1)
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<PcGts xmlns="{PAGE}" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<Metadata/><Page><TextRegion id=\"r1\">{lines}</TextRegion></Page></PcGts>"
    )
    return xml.encode("utf-8")


def one_line_alignment(text: str) -> Alignment:
    result = LineResult(1, text, text, text, 100.0, 1, text, "")
    return Alignment((result,), summarize((result,), 70), ())


def test_detect_namespace_returns_the_declared_schema() -> None:
    assert detect_namespace(parse_bytes(page_bytes("ברא"), max_bytes=4096).root) == PAGE


def test_detect_namespace_rejects_a_foreign_root_element() -> None:
    with pytest.raises(InvalidDocument):
        detect_namespace(etree.fromstring("<TEI/>"))


def test_detect_namespace_rejects_a_non_page_namespace() -> None:
    with pytest.raises(InvalidDocument):
        detect_namespace(etree.fromstring('<PcGts xmlns="urn:example"/>'))


def test_parse_pairs_every_line_with_the_element_it_came_from() -> None:
    document = parse_bytes(page_bytes("ברא", "ברא"), max_bytes=4096)
    assert [element.text for element in document.elements] == ["ברא", "ברא"]


def test_empty_lines_are_skipped_without_shifting_the_others() -> None:
    """The old code skipped empty lines on read, then re-walked every TextLine to write back."""
    document = parse_bytes(page_bytes("ברא", "", "ברא"), max_bytes=4096)
    assert document.line_count == 2
    assert [element.text for element in document.elements] == ["ברא", "ברא"]


def test_line_without_a_textequiv_layer_is_still_found() -> None:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<PcGts xmlns="{PAGE}"><Metadata/><Page>'
        f'<TextRegion id="r1"><TextLine id="l1"><Unicode>ברא</Unicode></TextLine></TextRegion>'
        f"</Page></PcGts>"
    )
    assert [element.text for element in parse_bytes(xml.encode(), max_bytes=4096).elements] == [
        "ברא"
    ]


def test_apply_alignment_writes_back_onto_the_source_element() -> None:
    document = parse_bytes(page_bytes("ברתשית"), max_bytes=4096)
    assert apply_alignment(document, one_line_alignment("בראשית")) == 1
    assert document.elements[0].text == "בראשית"


def test_apply_alignment_refuses_a_mismatched_result_set() -> None:
    document = parse_bytes(page_bytes("ברא", "ברא"), max_bytes=4096)
    with pytest.raises(InvalidDocument):
        apply_alignment(document, one_line_alignment("ברא"))


def test_text_scoring_below_the_floor_is_left_alone() -> None:
    document = parse_bytes(page_bytes("אבג"), max_bytes=4096)
    apply_alignment(document, one_line_alignment("צףץץץץ"), min_replace_score=99.0)
    assert document.elements[0].text == "אבג"


def test_apply_alignment_leaves_lastchange_untouched_when_nothing_changed() -> None:
    xml = page_bytes("ברא").replace(
        b"<Metadata/>",
        b"<Metadata><Creator>t</Creator><LastChange>2020-01-01T00:00:00</LastChange></Metadata>",
    )
    document = parse_bytes(xml, max_bytes=4096)
    apply_alignment(document, one_line_alignment("ברא"))
    stamps = [
        element.text
        for element in document.root.iter()
        if etree.QName(element).localname == "LastChange"
    ]
    assert stamps == ["2020-01-01T00:00:00"]


def test_apply_alignment_stamps_lastchange_when_it_writes() -> None:
    xml = page_bytes("ברא").replace(
        b"<Metadata/>",
        b"<Metadata><Creator>t</Creator><LastChange>2020-01-01T00:00:00</LastChange></Metadata>",
    )
    document = parse_bytes(xml, max_bytes=4096)
    apply_alignment(document, one_line_alignment("ברתשית"))
    stamps = [
        element.text
        for element in document.root.iter()
        if etree.QName(element).localname == "LastChange"
    ]
    assert stamps and stamps[0] != "2020-01-01T00:00:00"
    assert "+00:00" in stamps[0]


def test_serialize_uses_one_default_namespace_and_keeps_the_xsi_declaration() -> None:
    rendered = serialize(parse_bytes(page_bytes("ברא"), max_bytes=4096))
    assert rendered.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
    assert f'<PcGts xmlns="{PAGE}"'.encode() in rendered
    assert b"xmlns:xsi=" in rendered
    assert b"ns0:" not in rendered and b"<page:" not in rendered


def test_entity_references_are_not_expanded() -> None:
    """``resolve_entities=False`` is the lxml mitigation for entity-expansion bombs."""
    with_entity = page_bytes("ברא").replace(
        b"?>\n",
        b"?>\n<!DOCTYPE PcGts [<!ENTITY x \"SMUGGLED\">]>\n",
        1,
    ).replace("<Unicode>ברא</Unicode>".encode(), b"<Unicode>&x;</Unicode>")
    assert b"SMUGGLED" not in serialize(parse_bytes(with_entity, max_bytes=4096))


def test_malformed_document_is_rejected() -> None:
    with pytest.raises(InvalidDocument):
        parse_bytes(b"<PcGts", max_bytes=4096)


def test_empty_document_is_rejected() -> None:
    with pytest.raises(InvalidDocument):
        parse_bytes(b"   ", max_bytes=4096)


def test_oversized_document_is_rejected() -> None:
    with pytest.raises(FileTooLarge):
        parse_bytes(page_bytes("ברא"), max_bytes=10)


@pytest.mark.parametrize(
    "sample",
    ["BL_Or_1443_285.xml", "CBL_Ms._Heb_751_147.xml", "HCL_Ms._Sam._1_0008_a.xml"],
)
def test_every_committed_sample_parses(sample: str) -> None:
    data = (Path(__file__).resolve().parents[1] / "samples" / sample).read_bytes()
    document = parse_bytes(data, max_bytes=8 * 1024 * 1024)
    assert document.line_count > 0
    assert document.namespace is not None
    assert document.namespace.startswith(PAGE_SCHEMA_PREFIX)


def test_align_document_writes_corrected_xml(tmp_path: Path, xml_samples: list[Path]) -> None:
    source = xml_samples[0]
    data = source.read_bytes()
    texts = parse_bytes(data, max_bytes=8 * 1024 * 1024).texts
    outcome = align_document(
        source.name, data, ReferenceIndex(texts, max_span=1), out_dir=tmp_path
    )
    assert isinstance(outcome, DocumentOutcome)
    assert outcome.xml_path == tmp_path / "xml" / source.name
    assert outcome.alignment.summary.lines == len(texts)
    assert outcome.xml_path.read_bytes().startswith(b"<?xml")


def test_align_document_strips_directories_from_upload_names(tmp_path: Path) -> None:
    data = page_bytes("ברא")
    outcome = align_document(
        "../../etc/x.xml", data, ReferenceIndex(split_lines("ברא"), max_span=1), out_dir=tmp_path
    )
    assert outcome.filename == "x.xml"
    assert outcome.xml_path == tmp_path / "xml" / "x.xml"


def test_align_documents_reports_per_file_failures(tmp_path: Path, xml_samples: list[Path]) -> None:
    source = tmp_path / "in"
    source.mkdir()
    for file in xml_samples:
        (source / file.name).write_bytes(file.read_bytes())
    (source / "broken.xml").write_text("<PcGts", encoding="utf-8")

    outcomes, failures = align_documents(
        source, ReferenceIndex(["ברא"], max_span=1), out_dir=tmp_path / "out"
    )
    assert len(outcomes) == len(xml_samples)
    assert [failure.filename for failure in failures] == ["broken.xml"]
    assert isinstance(failures[0], DocumentFailure)


def test_align_documents_rejects_an_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(InvalidInput):
        align_documents(tmp_path / "empty", ReferenceIndex(["ברא"], max_span=1), out_dir=tmp_path)


def test_align_documents_enforces_the_file_limit(tmp_path: Path, xml_samples: list[Path]) -> None:
    source = tmp_path / "many"
    source.mkdir()
    for file in xml_samples:
        (source / file.name).write_bytes(file.read_bytes())
    with pytest.raises(InvalidInput):
        align_documents(source, ReferenceIndex(["ברא"], max_span=1), out_dir=tmp_path, limit=2)
