from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from conftest import PNG_BYTES
from ocrdiffalign.align import Alignment, LineResult, summarize
from ocrdiffalign.errors import FileTooLarge, InvalidDocument, InvalidInput
from ocrdiffalign.index import ReferenceIndex
from ocrdiffalign.pagexml import (
    PAGE_SCHEMA_PREFIX,
    DocumentFailure,
    DocumentOutcome,
    LineCrop,
    align_document,
    align_documents,
    apply_alignment,
    detect_namespace,
    parse_bytes,
    serialize,
    store_image,
)
from ocrdiffalign.text import split_lines

PAGE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"


def page_bytes(
    *texts: str,
    image: str | None = None,
    width: int = 1000,
    height: int = 100,
) -> bytes:
    """A minimal PAGE-XML document whose TextLines hold exactly ``texts``.

    Every line carries a 4-point ``Coords`` rectangle, and the page declares ``image`` with its
    ``width``/``height`` when an image name is given — as an OCR tool's export always does.
    """
    rows = []
    for number, text in enumerate(texts, start=1):
        top, bottom = number * 10, number * 10 + 8
        points = f"0,{top} 100,{top} 100,{bottom} 0,{bottom}"
        rows.append(
            f'<TextLine id="l{number}"><Coords points="{points}"/>'
            f"<TextEquiv><Unicode>{text}</Unicode></TextEquiv></TextLine>"
        )
    lines = "".join(rows)
    page_image = (
        f' imageFilename="{image}" imageWidth="{width}" imageHeight="{height}"' if image else ""
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<PcGts xmlns="{PAGE}" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<Metadata/><Page{page_image}><TextRegion id="r1">{lines}</TextRegion></Page></PcGts>'
    )
    return xml.encode("utf-8")


def one_line_alignment(ocr: str, match: str, score: float = 100.0) -> Alignment:
    result = LineResult(1, ocr, ocr, match, score, 1, match, "")
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
    assert [line.element.text for line in document.lines] == ["ברא", "ברא"]


def test_empty_lines_are_skipped_without_shifting_the_others() -> None:
    """The old code skipped empty lines on read, then re-walked every TextLine to write back."""
    document = parse_bytes(page_bytes("ברא", "", "ברא"), max_bytes=4096)
    assert document.line_count == 2
    assert [line.element.text for line in document.lines] == ["ברא", "ברא"]


def test_line_without_a_textequiv_layer_is_still_found() -> None:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<PcGts xmlns="{PAGE}"><Metadata/><Page>'
        f'<TextRegion id="r1"><TextLine id="l1"><Unicode>ברא</Unicode></TextLine></TextRegion>'
        f"</Page></PcGts>"
    )
    assert [line.element.text for line in parse_bytes(xml.encode(), max_bytes=4096).lines] == [
        "ברא"
    ]


def test_page_image_details_come_from_the_page_element() -> None:
    document = parse_bytes(
        page_bytes("ברא", image="doc.png", width=1751, height=2131), max_bytes=4096
    )
    assert (document.image_filename, document.image_width, document.image_height) == (
        "doc.png",
        1751,
        2131,
    )
    assert parse_bytes(page_bytes("ברא"), max_bytes=4096).image_filename is None


def test_a_line_keeps_its_own_polygon_verbatim() -> None:
    """A bounding box cannot express a skewed line, so the points are passed through unchanged."""
    document = parse_bytes(page_bytes("ברא", "ברא"), max_bytes=4096)
    assert [line.points for line in document.lines] == [
        "0,10 100,10 100,18 0,18",
        "0,20 100,20 100,28 0,28",
    ]


def test_a_line_without_coords_reports_no_polygon() -> None:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<PcGts xmlns="{PAGE}"><Metadata/><Page>'
        f'<TextRegion id="r1"><TextLine id="l1"><TextEquiv>'
        f"<Unicode>ברא</Unicode></TextEquiv></TextLine></TextRegion></Page></PcGts>"
    )
    assert parse_bytes(xml.encode(), max_bytes=4096).lines[0].points is None


def test_the_region_polygon_is_used_when_the_text_sits_on_the_region() -> None:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<PcGts xmlns="{PAGE}"><Metadata/>'
        f'<Page imageFilename="doc.png" imageWidth="9" imageHeight="9">'
        f'<TextRegion id="r1"><Coords points="1,2 3,4"/>'
        f"<TextEquiv><Unicode>ברא</Unicode></TextEquiv></TextRegion></Page></PcGts>"
    )
    document = parse_bytes(xml.encode(), max_bytes=4096)
    assert document.lines[0].points == "1,2 3,4"


def test_apply_alignment_writes_back_onto_the_source_element() -> None:
    document = parse_bytes(page_bytes("ברתשית"), max_bytes=4096)
    assert apply_alignment(document, one_line_alignment("ברתשית", "בראשית")) == 1
    assert document.lines[0].element.text == "בראשית"


def test_apply_alignment_refuses_a_mismatched_result_set() -> None:
    document = parse_bytes(page_bytes("ברא", "ברא"), max_bytes=4096)
    with pytest.raises(InvalidDocument):
        apply_alignment(document, one_line_alignment("ברא", "ברא"))


def test_text_scoring_below_the_floor_is_left_alone() -> None:
    document = parse_bytes(page_bytes("אבג"), max_bytes=4096)
    apply_alignment(
        document, one_line_alignment("אבג", "צףץץץץ", score=20.0), min_replace_score=99.0
    )
    assert document.lines[0].element.text == "אבג"


def test_apply_alignment_leaves_lastchange_untouched_when_nothing_changed() -> None:
    xml = page_bytes("ברא").replace(
        b"<Metadata/>",
        b"<Metadata><Creator>t</Creator><LastChange>2020-01-01T00:00:00</LastChange></Metadata>",
    )
    document = parse_bytes(xml, max_bytes=4096)
    apply_alignment(document, one_line_alignment("ברא", "ברא"))
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
    apply_alignment(document, one_line_alignment("ברא", "ברתשית"))
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
    with_entity = (
        page_bytes("ברא")
        .replace(
            b"?>\n",
            b'?>\n<!DOCTYPE PcGts [<!ENTITY x "SMUGGLED">]>\n',
            1,
        )
        .replace("<Unicode>ברא</Unicode>".encode(), b"<Unicode>&x;</Unicode>")
    )
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
    outcome = align_document(source.name, data, ReferenceIndex(texts), out_dir=tmp_path)
    assert isinstance(outcome, DocumentOutcome)
    assert outcome.xml_path == tmp_path / "xml" / source.name
    assert outcome.alignment.summary.lines == len(texts)
    assert outcome.xml_path.read_bytes().startswith(b"<?xml")


def test_align_document_strips_directories_from_upload_names(tmp_path: Path) -> None:
    data = page_bytes("ברא")
    outcome = align_document(
        "../../etc/x.xml", data, ReferenceIndex(split_lines("ברא")), out_dir=tmp_path
    )
    assert outcome.filename == "x.xml"
    assert outcome.xml_path == tmp_path / "xml" / "x.xml"


def test_store_image_writes_the_bytes_under_the_image_dir(tmp_path: Path) -> None:
    stored = store_image("page.png", PNG_BYTES, tmp_path)
    assert stored.parent == tmp_path / "images"
    assert stored.name.startswith("page-") and stored.suffix == ".png"
    assert stored.read_bytes() == PNG_BYTES


def test_every_stored_image_gets_its_own_file(tmp_path: Path) -> None:
    assert store_image("page.png", PNG_BYTES, tmp_path) != store_image(
        "page.png", PNG_BYTES, tmp_path
    )


@pytest.mark.parametrize("name", ["page.gif", "page.txt", "no_extension"])
def test_store_image_rejects_an_unsupported_extension(name: str, tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        store_image(name, PNG_BYTES, tmp_path)


def test_store_image_refuses_a_file_whose_header_denies_being_a_jpg(tmp_path: Path) -> None:
    """A ``.jpg`` holding PNG bytes would render as nothing, so it never reaches the output dir."""
    with pytest.raises(InvalidInput):
        store_image("page.jpg", PNG_BYTES, tmp_path)


def test_store_image_refuses_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        store_image("page.png", b"", tmp_path)


def test_store_image_refuses_an_oversized_file(tmp_path: Path) -> None:
    with pytest.raises(FileTooLarge):
        store_image("page.png", PNG_BYTES, tmp_path, max_bytes=4)


def test_store_image_needs_a_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        store_image("", PNG_BYTES, tmp_path)


def test_align_document_stores_the_named_image_and_crops_every_line(tmp_path: Path) -> None:
    data = page_bytes("ברא", "ברא", image="page.png")
    outcome = align_document(
        "doc.xml",
        data,
        ReferenceIndex(split_lines("ברא\nברא")),
        out_dir=tmp_path,
        images={"page.png": PNG_BYTES},
    )
    assert outcome.image_filename == "page.png"
    assert outcome.image_path is not None
    assert outcome.image_path.read_bytes() == PNG_BYTES
    assert (outcome.image_width, outcome.image_height) == (1000, 100)
    assert outcome.crops == (
        LineCrop(1, "0,10 100,10 100,18 0,18"),
        LineCrop(2, "0,20 100,20 100,28 0,28"),
    )


def test_align_document_matches_the_image_name_case_insensitively(tmp_path: Path) -> None:
    data = page_bytes("ברא", image="Page.PNG")
    outcome = align_document(
        "doc.xml", data, ReferenceIndex(["ברא"]), out_dir=tmp_path, images={"page.png": PNG_BYTES}
    )
    assert outcome.image_filename == "Page.PNG"
    assert outcome.image_path is not None


def test_align_document_without_the_named_image_still_aligns_but_has_no_crops(
    tmp_path: Path,
) -> None:
    data = page_bytes("ברא", image="page.png")
    outcome = align_document("doc.xml", data, ReferenceIndex(["ברא"]), out_dir=tmp_path)
    assert outcome.image_filename == "page.png"
    assert outcome.image_path is None
    assert outcome.crops == ()
    assert outcome.xml_path.exists()


def test_align_documents_reports_per_file_failures(tmp_path: Path, xml_samples: list[Path]) -> None:
    source = tmp_path / "in"
    source.mkdir()
    for file in xml_samples:
        (source / file.name).write_bytes(file.read_bytes())
    (source / "broken.xml").write_text("<PcGts", encoding="utf-8")

    outcomes, failures = align_documents(source, ReferenceIndex(["ברא"]), out_dir=tmp_path / "out")
    assert len(outcomes) == len(xml_samples)
    assert [failure.filename for failure in failures] == ["broken.xml"]
    assert isinstance(failures[0], DocumentFailure)


def test_align_documents_rejects_an_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(InvalidInput):
        align_documents(tmp_path / "empty", ReferenceIndex(["ברא"]), out_dir=tmp_path)


def test_align_documents_enforces_the_file_limit(tmp_path: Path, xml_samples: list[Path]) -> None:
    source = tmp_path / "many"
    source.mkdir()
    for file in xml_samples:
        (source / file.name).write_bytes(file.read_bytes())
    with pytest.raises(InvalidInput):
        align_documents(source, ReferenceIndex(["ברא"]), out_dir=tmp_path, limit=2)
