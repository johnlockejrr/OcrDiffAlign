"""PAGE-XML reading, correction and writing.

Three structural fixes over the previous scripts:

* Text is collected *with the elements it came from*. The old code extracted lines from some
  TextLines (skipping those without a ``Unicode`` child) and then re-walked every TextLine to
  write results back by counting, so one empty line shifted every later line onto the wrong
  element.
* Every line keeps the ``Coords`` polygon it occupies. A bounding box cannot show what the OCR
  tool actually read — the outline can be skewed, rotated or much shorter than its line — so the
  points are carried through verbatim for the client to crop with.
* Documents are parsed with ``resolve_entities=False``, which leaves external and internal
  entity definitions unexpanded (the standard lxml mitigation for entity-expansion bombs),
  and every payload is size-checked before parsing.

Both the stdlib ``xml.etree`` and ``lxml`` were used before; ``lxml`` alone is used now.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from .align import Alignment, align_lines, write_atomic
from .config import (
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_UPLOAD_BYTES,
    IMAGE_MEDIA_TYPES,
    IMAGE_SUFFIXES,
)
from .errors import FileTooLarge, InvalidDocument, InvalidInput, OcrDiffError
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


@dataclass(frozen=True)
class LineElement:
    """One OCR line: the ``Unicode`` element holding it and the polygon that line occupies."""

    element: etree._Element
    text: str
    points: str | None


@dataclass(frozen=True)
class ParsedDocument:
    """A parsed PAGE-XML file: its lines, and the page image the lines are drawn on."""

    root: etree._Element
    namespace: str | None
    lines: tuple[LineElement, ...]
    image_filename: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    @property
    def texts(self) -> tuple[str, ...]:
        """The OCR text of every line, in document order."""
        return tuple(line.text for line in self.lines)

    @property
    def line_count(self) -> int:
        return len(self.lines)


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


def _points_of(owner: etree._Element) -> str | None:
    """The owner's own ``Coords`` polygon, kept verbatim; ``None`` when it has none."""
    for coords in _direct_children(owner, "Coords"):
        points = (coords.get("points") or "").strip()
        if points:
            return points
    return None


def _direct_children(owner: etree._Element, name: str) -> list[etree._Element]:
    """Immediate children only, so a nested element's ``Coords`` is never read as the owner's."""
    return [child for child in owner if _localname(child) == name]


def _page_attribute(page: etree._Element | None, name: str) -> str | None:
    """A non-empty attribute of ``Page``, or ``None`` when it is absent or there is no page."""
    if page is None:
        return None
    return (page.get(name) or "").strip() or None


def _positive_int(raw: str | None) -> int | None:
    """Parse a positive integer attribute, tolerating the malformed values real files contain."""
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


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
    page = next(iter(_descendants(root, "Page")), None)

    owners: list[tuple[etree._Element, etree._Element]] = []
    lines = _descendants(root, "TextLine")
    if lines:
        owners = [(line, element) for line in lines for element in _equivalents_of(line)]
    else:
        # Some producers put the transcription on the region when there are no text lines.
        owners = [
            (region, element)
            for region in _descendants(root, "TextRegion")
            for element in _equivalents_of(region)
        ]

    parsed_lines = tuple(
        LineElement(element=element, text=(element.text or "").strip(), points=_points_of(owner))
        for owner, element in owners
    )
    return ParsedDocument(
        root=root,
        namespace=namespace,
        lines=parsed_lines,
        image_filename=_page_attribute(page, "imageFilename"),
        image_width=_positive_int(_page_attribute(page, "imageWidth")),
        image_height=_positive_int(_page_attribute(page, "imageHeight")),
    )


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
    if len(document.lines) != len(alignment.results):
        raise InvalidDocument(
            f"{len(document.lines)} text elements but {len(alignment.results)} alignments."
        )
    updated = 0
    for line, result in zip(document.lines, alignment.results, strict=True):
        if result.final_match == line.element.text:
            continue
        if result.score < min_replace_score:
            continue
        line.element.text = result.final_match
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


def _matches_header(suffix: str, data: bytes) -> bool:
    """Whether the file's first bytes agree with the extension it arrived with.

    Only a header check, never a decode: enough to refuse a ``.jpg`` that is really an HTML error
    page, without taking on an image library.
    """
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    return data[:4] in {b"II*\x00", b"MM\x00*"}


def store_image(
    filename: str,
    data: bytes,
    out_dir: Path,
    *,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> Path:
    """Validate one page image and store it, returning the path it was written to.

    The name only supplies the extension and a readable stem: the path is built server-side, so
    ``..`` and path separators in a client's string cannot escape the image dir.
    """
    supplied = Path(filename)
    if not supplied.name:
        raise InvalidInput("Image has no file name.")
    suffix = supplied.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(IMAGE_SUFFIXES))
        raise InvalidInput(f"{supplied.name}: supported extensions are {allowed}.")
    if not data:
        raise InvalidInput(f"{supplied.name} is empty.")
    if len(data) > max_bytes:
        raise FileTooLarge(f"{supplied.name} is {len(data)} bytes, limit is {max_bytes} bytes.")
    if not _matches_header(suffix, data[:8]):
        raise InvalidInput(f"{supplied.name} is not a readable {suffix} file.")

    target = Path(out_dir) / "images" / f"{supplied.stem}-{uuid.uuid4().hex[:8]}{suffix}"
    return write_atomic(target, data)


@dataclass(frozen=True)
class LineCrop:
    """The polygon one OCR line occupies, in the page image's coordinate space."""

    line_no: int
    points: str


@dataclass(frozen=True)
class DocumentOutcome:
    """One processed PAGE-XML file, plus its page image if one was supplied."""

    filename: str
    xml_path: Path
    alignment: Alignment
    updated_lines: int
    image_filename: str | None = None
    image_path: Path | None = None
    image_width: int | None = None
    image_height: int | None = None
    crops: tuple[LineCrop, ...] = ()
    image_error: str | None = None


@dataclass(frozen=True)
class DocumentFailure:
    """A file that could not be processed, with the reason."""

    filename: str
    message: str


def _attach_image(
    declared: str,
    images: Mapping[str, bytes] | None,
    out_dir: Path,
    max_image_bytes: int,
) -> tuple[Path | None, str | None]:
    """Store the image a document names, or say why it could not be stored.

    A rejected image is reported and left behind rather than raised: the alignment of the XML is
    already valid and saved, so losing the picture must not lose the result with it.
    """
    if not declared or images is None:
        return None, None
    blob = images.get(declared.casefold())
    if blob is None:
        return None, None
    try:
        return store_image(declared, blob, out_dir, max_bytes=max_image_bytes), None
    except OcrDiffError as exc:
        return None, exc.message


def align_document(
    filename: str,
    data: bytes,
    index: ReferenceIndex,
    *,
    out_dir: Path,
    threshold: int = 70,
    radius: int = DEFAULT_LINE_RADIUS,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    images: Mapping[str, bytes] | None = None,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> DocumentOutcome:
    """Align one document's OCR lines against ``index`` and save the corrected XML.

    ``images`` maps an available page image's casefolded file name to its bytes. The XML names its
    own image in ``Page@imageFilename``, so pairing is by that name rather than by upload order;
    when nothing matches, the XML is still aligned and saved and only the crops are missing.
    """
    safe_name = Path(filename).name
    if not safe_name:
        raise InvalidInput("Document has no file name.")
    document = parse_bytes(data, max_bytes=max_bytes)
    if not document.lines:
        raise InvalidDocument(f"{safe_name} contains no OCR text lines.")

    alignment = align_lines(document.texts, index, threshold=threshold, radius=radius)
    updated = apply_alignment(document, alignment)
    xml_path = write_atomic(Path(out_dir) / "xml" / safe_name, serialize(document))

    declared = document.image_filename or ""
    image_path, image_error = _attach_image(declared, images, Path(out_dir), max_image_bytes)
    crops = (
        ()
        if image_path is None
        else tuple(
            LineCrop(result.line_no, line.points)
            for result, line in zip(alignment.results, document.lines, strict=True)
            if line.points
        )
    )
    return DocumentOutcome(
        filename=safe_name,
        xml_path=xml_path,
        alignment=alignment,
        updated_lines=updated,
        image_filename=declared or None,
        image_path=image_path,
        image_width=document.image_width,
        image_height=document.image_height,
        crops=crops,
        image_error=image_error,
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
    "IMAGE_MEDIA_TYPES",
    "IMAGE_SUFFIXES",
    "KNOWN_PAGE_NAMESPACES",
    "MIN_REPLACE_SCORE",
    "DocumentFailure",
    "DocumentOutcome",
    "LineCrop",
    "LineElement",
    "ParsedDocument",
    "align_document",
    "align_documents",
    "apply_alignment",
    "detect_namespace",
    "parse_bytes",
    "serialize",
    "store_image",
]
