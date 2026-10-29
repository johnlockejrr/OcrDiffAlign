"""Error types shared by the engine and the HTTP layer.

Every failure the toolkit can produce is one of these, so the API can answer with a
stable machine-readable ``error`` code instead of a leaked Python traceback.
"""

from __future__ import annotations


class OcrDiffError(Exception):
    """Base class for expected failures. ``status_code`` is the HTTP status used for it."""

    error_code = "error"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"error": self.error_code, "message": self.message}


class NotFound(OcrDiffError):
    """A stored artefact the client asked for does not exist."""

    error_code = "not_found"
    status_code = 404


class InvalidReference(OcrDiffError):
    """The requested reference name is not a usable file inside the configured reference dir."""

    error_code = "invalid_reference"


class InvalidInput(OcrDiffError):
    """Client-supplied content could not be processed."""

    error_code = "invalid_input"


class FileTooLarge(OcrDiffError):
    """Content exceeds a configured size limit."""

    error_code = "file_too_large"
    status_code = 413


class InvalidDocument(OcrDiffError):
    """A PAGE-XML document could not be parsed or is not a PAGE-XML file."""

    error_code = "invalid_document"
