"""Runtime configuration.

Everything is resolved once from the environment so no path is ever taken from a request
without validation against ``ref_dir``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import InvalidInput, InvalidReference

DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_OCR_CHARS = 2_000_000
DEFAULT_MAX_XML_FILES = 64
DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
_REFERENCE_SUFFIX = ".txt"


def _discover_root() -> Path:
    """Project root: ``OCRDIFF_HOME`` if set, else the directory holding pyproject.toml."""
    env = os.environ.get("OCRDIFF_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd().resolve()


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _path_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return _resolve(raw) if raw else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise InvalidInput(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise InvalidInput(f"{name} must be positive, got {value}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes"}


def _origins_env(default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get("OCRDIFF_ALLOWED_ORIGINS")
    if not raw:
        return default
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    """Immutable application settings for one process."""

    root: Path
    ref_dir: Path
    output_dir: Path
    frontend_dir: Path | None = None
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_ocr_chars: int = DEFAULT_MAX_OCR_CHARS
    max_xml_files: int = DEFAULT_MAX_XML_FILES
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS
    debug: bool = False

    @classmethod
    def load(cls, root: str | Path | None = None) -> Settings:
        """Build settings from the environment; ``root`` overrides ``$OCRDIFF_HOME``."""
        resolved_root = _resolve(root) if root is not None else _discover_root()
        built_frontend = resolved_root / "frontend" / "dist"
        frontend_env = os.environ.get("OCRDIFF_FRONTEND_DIR")
        frontend_dir = (
            _resolve(frontend_env)
            if frontend_env
            else (built_frontend if built_frontend.is_dir() else None)
        )
        return cls(
            root=resolved_root,
            ref_dir=_path_env("OCRDIFF_REF_DIR", resolved_root / "ref"),
            output_dir=_path_env("OCRDIFF_OUTPUT_DIR", resolved_root / "aligned"),
            frontend_dir=frontend_dir,
            max_upload_bytes=_int_env("OCRDIFF_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
            max_ocr_chars=_int_env("OCRDIFF_MAX_OCR_CHARS", DEFAULT_MAX_OCR_CHARS),
            max_xml_files=_int_env("OCRDIFF_MAX_XML_FILES", DEFAULT_MAX_XML_FILES),
            allowed_origins=_origins_env(DEFAULT_ORIGINS),
            debug=_bool_env("OCRDIFF_DEBUG", False),
        )

    def with_overrides(
        self,
        *,
        ref_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        frontend_dir: str | Path | None = None,
        max_upload_bytes: int | None = None,
        max_ocr_chars: int | None = None,
        max_xml_files: int | None = None,
        debug: bool | None = None,
    ) -> Settings:
        """Copy with the given fields replaced; a ``None`` argument keeps the current value."""
        return replace(
            self,
            ref_dir=_resolve(ref_dir) if ref_dir is not None else self.ref_dir,
            output_dir=_resolve(output_dir) if output_dir is not None else self.output_dir,
            frontend_dir=_resolve(frontend_dir) if frontend_dir is not None else self.frontend_dir,
            max_upload_bytes=(
                max_upload_bytes if max_upload_bytes is not None else self.max_upload_bytes
            ),
            max_ocr_chars=max_ocr_chars if max_ocr_chars is not None else self.max_ocr_chars,
            max_xml_files=max_xml_files if max_xml_files is not None else self.max_xml_files,
            debug=debug if debug is not None else self.debug,
        )

    def list_references(self) -> tuple[str, ...]:
        """Names of every usable reference file, sorted, ignoring symlinks and strays."""
        if not self.ref_dir.is_dir():
            return ()
        names: list[str] = []
        for entry in self.ref_dir.iterdir():
            if not entry.is_file() or entry.is_symlink():
                continue
            if entry.suffix != _REFERENCE_SUFFIX or entry.name.startswith("."):
                continue
            names.append(entry.name)
        return tuple(sorted(names))

    def resolve_reference(self, name: str) -> Path:
        """Resolve a reference name or path to a real file, refusing anything outside ``ref_dir``.

        A request may pass ``ref`` as a bare name (``schorch_verses.txt``) or as a path
        (``ref/schorch_verses.txt``). Both are confined to ``ref_dir`` so ``../../etc/passwd``
        and absolute paths outside the reference dir cannot be read.
        """
        candidate = (name or "").strip()
        if not candidate:
            raise InvalidReference("Reference name must not be empty.")

        supplied = Path(candidate)
        attempts = [supplied] if supplied.is_absolute() else [self.ref_dir / supplied, supplied]
        for path in attempts:
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix != _REFERENCE_SUFFIX:
                continue
            if _within(path.resolve(), self.ref_dir):
                return path.resolve()

        known = ", ".join(self.list_references()) or "none"
        raise InvalidReference(f"Unknown reference {candidate!r}. Available references: {known}")


def _within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True
