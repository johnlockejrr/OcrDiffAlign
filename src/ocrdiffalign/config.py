"""Runtime configuration.

Everything is resolved once from the environment (or explicit overrides for tests) so
no path is ever taken from a request without validation against ``ref_dir``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import InvalidReference, InvalidInput

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
    def load(cls, **overrides: object) -> Settings:
        """Build settings from the environment, with keyword overrides taking precedence."""
        root = Path(str(overrides.get("root") or _discover_root())).expanduser().resolve()
        ref_dir = Path(
            str(
                overrides.get("ref_dir")
                or os.environ.get("OCRDIFF_REF_DIR")
                or root / "ref"
            )
        ).expanduser().resolve()
        output_dir = Path(
            str(
                overrides.get("output_dir")
                or os.environ.get("OCRDIFF_OUTPUT_DIR")
                or root / "aligned"
            )
        ).expanduser().resolve()

        frontend_raw = overrides.get("frontend_dir") or os.environ.get("OCRDIFF_FRONTEND_DIR")
        if frontend_raw is None:
            built = root / "frontend" / "dist"
            frontend_dir: Path | None = built if built.is_dir() else None
        elif str(frontend_raw) == "":
            frontend_dir = None
        else:
            frontend_dir = Path(str(frontend_raw)).expanduser().resolve()

        origins_raw = overrides.get("allowed_origins") or os.environ.get("OCRDIFF_ALLOWED_ORIGINS")
        if origins_raw is None:
            origins: tuple[str, ...] = DEFAULT_ORIGINS
        elif isinstance(origins_raw, (tuple, list)):
            origins = tuple(str(o) for o in origins_raw)
        else:
            origins = tuple(o.strip() for o in str(origins_raw).split(",") if o.strip())

        debug_raw = overrides.get("debug")
        debug = (
            os.environ.get("OCRDIFF_DEBUG", "").lower() in {"1", "true", "yes"}
            if debug_raw is None
            else bool(debug_raw)
        )

        return cls(
            root=root,
            ref_dir=ref_dir,
            output_dir=output_dir,
            frontend_dir=frontend_dir,
            max_upload_bytes=int(  # type: ignore[arg-type]
                overrides.get("max_upload_bytes")
                or _int_env("OCRDIFF_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
            ),
            max_ocr_chars=int(  # type: ignore[arg-type]
                overrides.get("max_ocr_chars")
                or _int_env("OCRDIFF_MAX_OCR_CHARS", DEFAULT_MAX_OCR_CHARS)
            ),
            max_xml_files=int(  # type: ignore[arg-type]
                overrides.get("max_xml_files")
                or _int_env("OCRDIFF_MAX_XML_FILES", DEFAULT_MAX_XML_FILES)
            ),
            allowed_origins=origins,
            debug=debug,
        )

    def with_overrides(self, **overrides: object) -> Settings:
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})

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
            resolved = path.resolve() if path.exists() else path
            if not str(resolved).endswith(_REFERENCE_SUFFIX):
                continue
            if path.is_file() and not path.is_symlink():
                resolved = path.resolve()
                if _within(resolved, self.ref_dir):
                    return resolved

        known = ", ".join(self.list_references()) or "none"
        raise InvalidReference(f"Unknown reference {candidate!r}. Available references: {known}")


def _within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True
