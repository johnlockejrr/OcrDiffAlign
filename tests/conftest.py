from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocrdiffalign.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
REF_DIR = REPO_ROOT / "ref"
SAMPLES_DIR = REPO_ROOT / "samples"

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
