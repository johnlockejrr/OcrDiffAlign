from __future__ import annotations

from pathlib import Path

import pytest

from ocrdiffalign import __version__
from ocrdiffalign.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
OCR_SAMPLE = REPO_ROOT / "samples" / "ocr.txt"
SAMPLES = REPO_ROOT / "samples"


def test_align_command_writes_three_artefacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--home",
            str(REPO_ROOT),
            "align",
            "--ocr",
            str(OCR_SAMPLE),
            "--ref",
            "schorch_verses.txt",
            "--out",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    printed = capsys.readouterr().out
    assert "Lines processed:" in printed
    assert len(list(tmp_path.iterdir())) == 3


def test_pagexml_command_processes_a_whole_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--home",
            str(REPO_ROOT),
            "pagexml",
            "--pagexml",
            str(SAMPLES),
            "--ref",
            "schorch_verses.txt",
            "--out",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert len(list((tmp_path / "xml").glob("*.xml"))) == 3


def test_unknown_reference_exits_with_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--home",
            str(REPO_ROOT),
            "align",
            "--ocr",
            str(OCR_SAMPLE),
            "--ref",
            "nope.txt",
            "--out",
            str(tmp_path),
        ]
    )
    assert exit_code == 2
    assert "Unknown reference" in capsys.readouterr().err


def test_missing_ocr_file_exits_with_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--home",
            str(REPO_ROOT),
            "align",
            "--ocr",
            str(tmp_path / "none.txt"),
            "--ref",
            "schorch_verses.txt",
        ]
    )
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_missing_pagexml_path_exits_with_code_two(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--home",
            str(REPO_ROOT),
            "pagexml",
            "--pagexml",
            "/nonexistent/dir",
            "--ref",
            "schorch_verses.txt",
        ]
    )
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("threshold", ["-1", "101", "not-a-number"])
def test_threshold_must_be_a_percentage(threshold: str) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "align",
                "--ocr",
                str(OCR_SAMPLE),
                "--ref",
                "schorch_verses.txt",
                "--threshold",
                threshold,
            ]
        )


def test_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["--version"])
    assert exited.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_a_subcommand_is_required() -> None:
    with pytest.raises(SystemExit):
        main([])
