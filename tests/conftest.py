from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest

from ocrdiffalign.config import IMAGE_MEDIA_TYPES, Settings
from ocrdiffalign.pagexml import parse_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
REF_DIR = REPO_ROOT / "ref"
SAMPLES_DIR = REPO_ROOT / "samples"

# A 1x1 PNG. Image validation checks headers only, so no decoder is needed to hold one; a fake
# JPEG needs nothing more than its magic bytes for the same reason.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"OcrDiffAlign test image"
_IMAGE_BYTES = {".png": PNG_BYTES, ".jpg": JPEG_BYTES}


def upload_for(xml_path: Path) -> tuple[str, bytes, str]:
    """The image ``xml_path`` declares, as the tuple a client would upload it with.

    The XML names its own image, and the server checks that what arrives really is that kind of
    file — so the name and the bytes have to agree.
    """
    declared = parse_bytes(xml_path.read_bytes(), max_bytes=8 * 1024 * 1024).image_filename or ""
    suffix = Path(declared).suffix.lower()
    if suffix not in _IMAGE_BYTES:
        raise AssertionError(f"{xml_path.name} declares {declared!r}; no test bytes for it.")
    return declared, _IMAGE_BYTES[suffix], IMAGE_MEDIA_TYPES[suffix]


MINI_REFERENCE = "\n".join(
    [
        "בראשית ברא האלהים את השמים",
        "ויאמר אלהים יהי מארת",
        "ויבדל בין המים",
        "יקרא ליום אור",
        "ולילוק קרא חשך",
    ]
)


@pytest.fixture
def mini_reference_text() -> str:
    return MINI_REFERENCE


@pytest.fixture
def png_bytes() -> bytes:
    return PNG_BYTES


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at the repo's real references, writing output into a temp dir."""
    return Settings(
        root=REPO_ROOT,
        ref_dir=REF_DIR,
        output_dir=tmp_path / "aligned",
        frontend_dir=None,
        max_upload_bytes=64 * 1024 * 1024,
        max_ocr_chars=1_000_000,
        max_xml_files=4,
        debug=True,
    )


@pytest.fixture
def ref_path() -> Path:
    return REF_DIR / "schorch_verses.txt"


@pytest.fixture
def ocr_sample() -> str:
    return (SAMPLES_DIR / "ocr.txt").read_text(encoding="utf-8")


@pytest.fixture
def xml_samples() -> list[Path]:
    return sorted(SAMPLES_DIR.glob("*.xml"))


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """A copy of ``samples/`` so tests never write into the repository."""
    target = tmp_path / "samples"
    target.mkdir()
    for file in sorted(SAMPLES_DIR.glob("*.xml")):
        shutil.copy(file, target / file.name)
    return target
