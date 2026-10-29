"""HTTP surface: schemas, routes, error handling and the app factory.

The API mirrors what the Svelte client needs and nothing more. Every reference name in a
request is validated against ``Settings.ref_dir`` before it touches the filesystem, and every
expected failure is answered with ``{"error": <code>, "message": <text>}`` rather than a
traceback, so the client can show the real reason and nothing internal leaks out.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .align import Alignment, Confusion, LineResult, Summary, align_text, summarize
from .config import IMAGE_MEDIA_TYPES, Settings
from .errors import FileTooLarge, InvalidInput, OcrDiffError
from .index import load_reference
from .pagexml import align_document

logger = logging.getLogger("ocrdiffalign")

MAX_LOGGED_VALIDATION_ERRORS = 5
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


class RequestModel(BaseModel):
    """Input schemas reject unknown keys, so a client-side typo fails instead of being ignored."""

    model_config = ConfigDict(extra="forbid")


class LineResultModel(RequestModel):
    line_no: int = Field(ge=1)
    ocr: str
    normalized: str
    match: str
    score: float = Field(ge=0, le=100)
    ref_index: int = Field(ge=0)
    final_match: str
    diff_html: str


class SummaryModel(RequestModel):
    lines: int = Field(ge=0)
    average_score: float = Field(ge=0, le=100)
    threshold: int = Field(ge=0, le=100)
    low_count: int = Field(ge=0)
    low_pct: float = Field(ge=0, le=100)


class ConfusionModel(RequestModel):
    ocr_char: str
    ref_char: str
    count: int = Field(ge=1)


class AlignRequest(RequestModel):
    ref: str = Field(min_length=1, max_length=500)
    ocr_text: str = Field(min_length=1)
    threshold: int = Field(default=70, ge=0, le=100)


class ExportRequest(BaseModel):
    """Lenient on purpose: the client round-trips server output back to this endpoint.

    ``threshold`` is optional so an edited run can be persisted without resending it.
    """

    model_config = ConfigDict(extra="ignore")

    ref: str = Field(min_length=1, max_length=500)
    results: list[LineResultModel] = Field(min_length=1)
    confusions: list[ConfusionModel] = Field(default_factory=list)
    threshold: int = Field(default=70, ge=0, le=100)


class ArtifactSet(BaseModel):
    csv: str
    txt: str
    confusions_csv: str


class AlignResponse(BaseModel):
    results: list[LineResultModel]
    summary: SummaryModel
    confusions: list[ConfusionModel]
    files: ArtifactSet
    paths: ArtifactSet


class RefEntry(BaseModel):
    name: str
    size_bytes: int = Field(ge=0)


class RefsResponse(BaseModel):
    refs: list[RefEntry]


class LineCropModel(BaseModel):
    """The ``TextLine`` polygon for one result line, in the page image's coordinate space."""

    line_no: int = Field(ge=1)
    points: str = Field(min_length=1)


class DocumentModel(BaseModel):
    filename: str
    xml_path: str
    summary: SummaryModel
    results: list[LineResultModel]
    image_filename: str | None = None
    image_url: str | None = None
    image_width: int | None = Field(default=None, ge=1)
    image_height: int | None = Field(default=None, ge=1)
    image_error: str | None = None
    crops: list[LineCropModel] = []


class DocumentFailureModel(BaseModel):
    filename: str
    message: str


class PagexmlResponse(BaseModel):
    documents: list[DocumentModel]
    errors: list[DocumentFailureModel]


class ExportResponse(BaseModel):
    csv: str
    txt: str
    confusions_csv: str
    csv_path: str
    txt_path: str
    confusions_path: str


class HealthResponse(BaseModel):
    status: str
    version: str


def _image_url(path: Path | None) -> str | None:
    """The URL a stored page image is served from, or ``None`` when there is none."""
    return f"/api/image?name={quote(path.name)}" if path is not None else None


def _lines(results: Sequence[LineResult]) -> list[LineResultModel]:
    return [LineResultModel(**asdict(result)) for result in results]


def _confusions(confusions: Sequence[Confusion]) -> list[ConfusionModel]:
    return [ConfusionModel(**asdict(confusion)) for confusion in confusions]


def _summary(summary: Summary) -> SummaryModel:
    return SummaryModel(**asdict(summary))


def _stem(reference: Path) -> str:
    """Output stem such as ``schorch_verses-9f3c1a2e``: named after the reference used."""
    return f"{reference.stem}-{uuid.uuid4().hex[:8]}"


def build_router(settings: Settings) -> APIRouter:
    """All ``/api`` routes, closed over the settings they serve."""
    router = APIRouter(prefix="/api")

    def aligned_document(
        filename: str,
        data: bytes,
        reference: Path,
        threshold: int,
        images: Mapping[str, bytes] | None = None,
    ) -> DocumentModel:
        outcome = align_document(
            filename,
            data,
            load_reference(reference),
            out_dir=settings.output_dir,
            threshold=threshold,
            max_bytes=settings.max_upload_bytes,
            images=images,
            max_image_bytes=settings.max_image_bytes,
        )
        return DocumentModel(
            filename=outcome.filename,
            xml_path=str(outcome.xml_path),
            summary=_summary(outcome.alignment.summary),
            results=_lines(outcome.alignment.results),
            image_filename=outcome.image_filename,
            image_url=_image_url(outcome.image_path),
            image_width=outcome.image_width,
            image_height=outcome.image_height,
            image_error=outcome.image_error,
            crops=[LineCropModel(**asdict(crop)) for crop in outcome.crops],
        )

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @router.get("/refs", response_model=RefsResponse)
    def refs() -> RefsResponse:
        entries = [
            RefEntry(name=name, size_bytes=(settings.ref_dir / name).stat().st_size)
            for name in settings.list_references()
        ]
        return RefsResponse(refs=entries)

    @router.post("/align", response_model=AlignResponse)
    def align(payload: AlignRequest) -> AlignResponse:
        reference = settings.resolve_reference(payload.ref)
        if len(payload.ocr_text) > settings.max_ocr_chars:
            raise FileTooLarge(
                f"OCR text is {len(payload.ocr_text)} characters, "
                f"limit is {settings.max_ocr_chars}."
            )
        alignment = align_text(payload.ocr_text, reference, threshold=payload.threshold)
        paths = alignment.save(settings.output_dir, stem=_stem(reference))
        return AlignResponse(
            results=_lines(alignment.results),
            summary=_summary(alignment.summary),
            confusions=_confusions(alignment.confusions),
            files=ArtifactSet(
                csv=alignment.csv(),
                txt=alignment.matched_text(),
                confusions_csv=alignment.confusions_csv(),
            ),
            paths=ArtifactSet(
                csv=str(paths["csv"]),
                txt=str(paths["txt"]),
                confusions_csv=str(paths["confusions_csv"]),
            ),
        )

    @router.post("/export", response_model=ExportResponse)
    def export(payload: ExportRequest) -> ExportResponse:
        reference = settings.resolve_reference(payload.ref)
        results = tuple(LineResult(**model.model_dump()) for model in payload.results)
        confusions = tuple(Confusion(**model.model_dump()) for model in payload.confusions)
        alignment = Alignment(
            results=results,
            summary=summarize(results, payload.threshold),
            confusions=confusions,
        )
        paths = alignment.save(settings.output_dir, stem=_stem(reference))
        return ExportResponse(
            csv=alignment.csv(),
            txt=alignment.matched_text(),
            confusions_csv=alignment.confusions_csv(),
            csv_path=str(paths["csv"]),
            txt_path=str(paths["txt"]),
            confusions_path=str(paths["confusions_csv"]),
        )

    @router.get("/image")
    def image(name: Annotated[str, Query(min_length=1, max_length=255)]) -> FileResponse:
        path = settings.resolve_stored_image(name)
        return FileResponse(path, media_type=IMAGE_MEDIA_TYPES[Path(name).suffix.lower()])

    @router.post("/pagexml", response_model=PagexmlResponse)
    async def pagexml(
        ref: Annotated[str, Form(min_length=1, max_length=500)],
        files: Annotated[list[UploadFile], File()],
        threshold: Annotated[int, Form(ge=0, le=100)] = 70,
        images: list[UploadFile] = File(default=[]),
    ) -> PagexmlResponse:
        reference = settings.resolve_reference(ref)
        if not files:
            raise InvalidInput("Upload at least one PAGE-XML file.")
        if len(files) > settings.max_xml_files:
            raise FileTooLarge(
                f"{len(files)} files uploaded, limit is {settings.max_xml_files} per request."
            )
        if len(images) > settings.max_xml_files:
            raise FileTooLarge(
                f"{len(images)} images uploaded, limit is {settings.max_xml_files} per request."
            )

        # Each XML names its own image, so uploads are keyed by name and matched per document;
        # images that belong to no uploaded XML are read but unused.
        image_bytes: dict[str, bytes] = {}
        for upload in images:
            name = Path(upload.filename or "").name
            if not name:
                continue
            try:
                image_bytes.setdefault(
                    name.casefold(), await upload.read(settings.max_image_bytes + 1)
                )
            except OSError as exc:
                raise InvalidInput(f"{name} could not be read.") from exc
            finally:
                await upload.close()

        documents: list[DocumentModel] = []
        errors: list[DocumentFailureModel] = []
        for upload in files:
            name = Path(upload.filename or "").name
            try:
                if not name.endswith(".xml"):
                    raise InvalidInput(f"{name or 'upload'} is not an .xml file.")
                data = await upload.read(settings.max_upload_bytes + 1)
                if len(data) > settings.max_upload_bytes:
                    raise FileTooLarge(f"{name} is larger than {settings.max_upload_bytes} bytes.")
                documents.append(aligned_document(name, data, reference, threshold, image_bytes))
            except OcrDiffError as exc:
                errors.append(DocumentFailureModel(filename=name, message=exc.message))
            finally:
                await upload.close()

        return PagexmlResponse(documents=documents, errors=errors)

    return router


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware adding the response headers a tool like this should always send.

    The CSP is applied only to non-API responses: API payloads are JSON or file contents that
    the client renders as text, so ``script-src 'self'`` would buy nothing there while
    ``Cache-Control: no-store`` keeps a shared cache from serving stale results.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        apply_csp = not path.startswith("/api")
        # A stored image's name contains a random suffix, so the name changes whenever the content
        # does and the asset itself never needs revalidating. Caching it also matters for the page:
        # every visible row references the same URL, and without this each crop would refetch it.
        cache_control = b"private, max-age=86400" if path.startswith("/api/image") else b"no-store"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {name.lower() for name, _ in headers}
                wanted = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"cache-control": cache_control,
                }
                if apply_csp:
                    wanted[b"content-security-policy"] = _CONTENT_SECURITY_POLICY.encode()
                for name, value in wanted.items():
                    if name not in existing:
                        headers.append((name, value))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own ``Settings`` to point at temporary dirs."""
    settings = settings or Settings.load()

    app = FastAPI(
        title="OcrDiffAlign",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(OcrDiffError)
    async def handle_known_error(_: Request, exc: OcrDiffError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for error in exc.errors()[:MAX_LOGGED_VALIDATION_ERRORS]:
            location = ".".join(str(part) for part in error.get("loc", ())[1:])
            message = str(error.get("msg", "Invalid value."))
            parts.append(f"{location}: {message}" if location else message)
        joined = "; ".join(parts) or "Invalid request."
        logger.debug("Validation failed: %s", joined)
        return JSONResponse(
            status_code=422, content={"error": "invalid_request", "message": joined}
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        message = f"{type(exc).__name__}: {exc}" if settings.debug else "Internal server error."
        return JSONResponse(
            status_code=500, content={"error": "internal_error", "message": message}
        )

    app.include_router(build_router(settings))

    if settings.frontend_dir is not None:
        app.mount(
            "/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend"
        )
    else:

        @app.get("/", include_in_schema=False)
        def frontend_not_built() -> JSONResponse:
            return JSONResponse(
                status_code=200,
                content={
                    "service": "OcrDiffAlign",
                    "version": __version__,
                    "frontend": "not built",
                    "hint": "Run 'npm run build' in frontend/, or open the API docs at /api/docs.",
                },
            )

    return app


app = create_app()

__all__ = ["Settings", "app", "build_router", "create_app"]
