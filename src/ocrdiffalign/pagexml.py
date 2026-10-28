"""PAGE-XML reading, correction and writing.

Two structural fixes over the previous scripts:

* Text is collected *with the elements it came from*. The old code extracted lines from some
  TextLines (skipping those without a ``Unicode`` child) and then re-walked every TextLine to
  write results back by counting, so one empty line shifted every later line onto the wrong
  element.
* Documents are parsed with ``resolve_entities=False``, which leaves external and internal
  entity definitions unexpanded (the standard lxml mitigation for entity-expansion bombs),
  and every payload is size-checked before parsing.

Both the stdlib ``xml.etree`` and ``lxml`` were used before; ``lxml`` alone is used now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from .align import Alignment, align_lines, write_atomic
from .config import DEFAULT_MAX_UPLOAD_BYTES
from .errors import FileTooLarge, InvalidDocument, InvalidInput
from .index import DEFAULT_LINE_RADIUS, ReferenceIndex

PAGE_SCHEMA_PREFIX = "http://schema.primaresearch.org/PAGE/gts/pagecontent/"
KNOWN_PAGE_NAMESPACES: tuple[str, ...] = (
    "2009-03-16",
    "2010-01-12",
    "2010-03-19",
    "2013-07-15",
    "2014-08-26",
    "2016-07-15",
    "2017-07-15",
    "2018-07-15",
    "2019-07-15",
)
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Below this score the OCR text is left alone rather than overwritten with a guess.
MIN_REPLACE_SCORE = 50.0


@dataclass
class ParsedDocument:
    """A parsed PAGE-XML file and the ``Unicode`` elements its OCR lines came from."""

    root: etree._Element
    namespace: str | None
    elements: tuple[etree._Element, ...]
    texts: tuple[str, ...]

    @property
    def line_count(self) -> int:
        return len(self.texts)


def _localname(element: etree._Element) -> str:
    """Tag without its namespace prefix.

    ``iter()`` also yields entity, comment and processing-instruction nodes, whose ``tag`` is
    not a string; those never match a name, so they are reported as having no name at all.
    """
    tag = element.tag if isinstance(element.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _namespace_of(element: etree._Element) -> str | None:
    """Namespace URI of an element, or ``None`` if it has none or is not a real element."""
    tag = element.tag if isinstance(element.tag, str) else ""
    if not tag.startswith("{"):
        return None
    return tag[1:].partition("}")[0] or None


def _descendants(root: etree._Element, name: str) -> list[etree._Element]:
    return [element for element in root.iter() if _localname(element) == name]


def _nsmap_for(root: etree._Element, default_namespace: str | None) -> dict[str | None, str]:
    """Every prefix used anywhere in the tree, so no serialised child needs a generated one."""
    nsmap: dict[str | None, str] = {}
    if default_namespace:
        nsmap[None] = default_namespace
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for prefix, uri in element.nsmap.items():
            if prefix and prefix not in nsmap:
                nsmap[prefix] = uri
    return nsmap


def detect_namespace(root: etree._Element) -> str | None:
    """Return the document's namespace, validating that it is a PAGE-XML document."""
    if _localname(root) != "PcGts":
        raise InvalidDocument(f"Root element is {_localname(root)!r}, expected 'PcGts'.")

    namespace = _namespace_of(root)
    if not namespace:
        return None
    if not namespace.startswith(PAGE_SCHEMA_PREFIX):
        raise InvalidDocument(f"Namespace {namespace!r} is not a PAGE-XML content schema.")
    return namespace


def parse_bytes(data: bytes, *, max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> ParsedDocument:
    """Parse PAGE-XML bytes and pair every OCR line with the element holding it."""
    if len(data) > max_bytes:
        raise FileTooLarge(f"Document is {len(data)} bytes, limit is {max_bytes} bytes.")
    if not data.strip():
        raise InvalidDocument("Document is empty.")

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise InvalidDocument(f"Malformed XML: {exc.msg}") from None
    if not isinstance(root, etree._Element):
        raise InvalidDocument("Document has no root element.")

    namespace = detect_namespace(root)

    lines = _descendants(root, "TextLine")
    if lines:
        elements = tuple(element for line in lines for element in _equivalents_of(line))
    else:
        # Some producers put the transcription on the region when there are no text lines.
        elements = tuple(
            element
            for region in _descendants(root, "TextRegion")
            for element in _equivalents_of(region)
        )

    texts = tuple((element.text or "").strip() for element in elements)
    return ParsedDocument(root=root, namespace=namespace, elements=elements, texts=texts)


def _equivalents_of(owner: etree._Element) -> list[etree._Element]:
    """``Unicode`` elements under a TextLine/TextRegion, honouring any TextEquiv layer."""
    found: list[etree._Element] = []
    for text_equiv in _descendants(owner, "TextEquiv"):
        found.extend(child for child in text_equiv.iter() if _localname(child) == "Unicode")
    if not found:
        found = [child for child in owner.iter() if _localname(child) == "Unicode"]
    return [element for element in found if (element.text or "").strip()]


def apply_alignment(
    document: ParsedDocument,
    alignment: Alignment,
    *,
    min_replace_score: float = MIN_REPLACE_SCORE,
) -> int:
    """Write each aligned match back onto the element it came from. Returns lines changed."""
    if len(document.elements) != len(alignment.results):
        raise InvalidDocument(
            f"{len(document.elements)} text elements but {len(alignment.results)} alignments."
        )
    updated = 0
    for element, result in zip(document.elements, alignment.results, strict=True):
        if result.final_match == element.text:
            continue
        if result.score < min_replace_score:
            continue
        element.text = result.final_match
        updated += 1

    if updated:
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for last_change in _descendants(document.root, "LastChange"):
            last_change.text = stamp
    return updated


def serialize(document: ParsedDocument) -> bytes:
    """Serialise without namespace prefixes, keeping a single default declaration.

    Element children only: entity, comment and processing-instruction nodes have no element to
    recreate, so an unexpanded entity reference is dropped rather than resolved.
    """
    nsmap = _nsmap_for(document.root, document.namespace)

    def clone(source: etree._Element, parent: etree._Element | None) -> etree._Element:
        namespace, local = _namespace_of(source), _localname(source)
        tag = f"{{{namespace}}}{local}" if namespace else local
        target = (
            etree.Element(tag, nsmap=nsmap) if parent is None else etree.SubElement(parent, tag)
        )
        for key, value in source.attrib.items():
            target.set(key, value)
        target.text = source.text
        target.tail = source.tail
        for child in source:
            if isinstance(child.tag, str):
                clone(child, target)
        return target

    rendered: bytes = etree.tostring(
        clone(document.root, None), encoding="utf-8", pretty_print=True
    )
    return XML_DECLARATION + rendered


@dataclass(frozen=True)
class DocumentOutcome:
    """One processed PAGE-XML file."""

    filename: str
    xml_path: Path
    alignment: Alignment
    updated_lines: int


@dataclass(frozen=True)
class DocumentFailure:
    """A file that could not be processed, with the reason."""

    filename: str
    message: str


def align_document(
    filename: str,
    data: bytes,
    index: ReferenceIndex,
    *,
    out_dir: Path,
    threshold: int = 70,
    radius: int = DEFAULT_LINE_RADIUS,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> DocumentOutcome:
    """Align one document's OCR lines against ``index`` and save the corrected XML."""
    safe_name = Path(filename).name
    if not safe_name:
        raise InvalidInput("Document has no file name.")
    document = parse_bytes(data, max_bytes=max_bytes)
    if not document.elements:
        raise InvalidDocument(f"{safe_name} contains no OCR text lines.")

    alignment = align_lines(document.texts, index, threshold=threshold, radius=radius)
    updated = apply_alignment(document, alignment)
    xml_path = write_atomic(Path(out_dir) / "xml" / safe_name, serialize(document).decode("utf-8"))
    return DocumentOutcome(
        filename=safe_name,
        xml_path=xml_path,
        alignment=alignment,
        updated_lines=updated,
    )


def align_documents(
    source: Path,
    index: ReferenceIndex,
    *,
    out_dir: Path,
    threshold: int = 70,
    limit: int = 64,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> tuple[list[DocumentOutcome], list[DocumentFailure]]:
    """Process a PAGE-XML file or a whole directory of them."""
    source = Path(source)
    if source.is_file():
        files = [(source.name, source)]
    elif source.is_dir():
        files = [(path.name, path) for path in sorted(source.glob("*.xml"))]
        if not files:
            raise InvalidInput(f"No .xml files found in {source}.")
        if len(files) > limit:
            raise InvalidInput(f"{len(files)} files found, limit is {limit} per run.")
    else:
        raise InvalidInput(f"{source} does not exist.")

    outcomes: list[DocumentOutcome] = []
    failures: list[DocumentFailure] = []
    for filename, path in files:
        try:
            data = path.read_bytes()
        except OSError as exc:
            failures.append(DocumentFailure(filename=filename, message=str(exc)))
            continue
        try:
            outcomes.append(
                align_document(
                    filename,
                    data,
                    index,
                    out_dir=out_dir,
                    threshold=threshold,
                    max_bytes=max_bytes,
                )
            )
        except Exception as exc:  # a bad file must not abort the whole batch
            failures.append(DocumentFailure(filename=filename, message=str(exc)))
    return outcomes, failures


__all__ = [
    "KNOWN_PAGE_NAMESPACES",
    "MIN_REPLACE_SCORE",
    "DocumentFailure",
    "DocumentOutcome",
    "ParsedDocument",
    "align_document",
    "align_documents",
    "apply_alignment",
    "detect_namespace",
    "parse_bytes",
    "serialize",
]
