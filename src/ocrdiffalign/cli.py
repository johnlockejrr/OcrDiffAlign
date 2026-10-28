"""Command-line interface: align a text file, align PAGE-XML, or serve the web app.

Replaces the three root scripts (``align.py``, ``align-pagexml.py``,
``align-pagexml-index.py``) with subcommands over one engine, so the CLI and the web app can
no longer drift apart.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import __version__
from .align import align_text, format_report
from .config import Settings
from .errors import OcrDiffError
from .index import load_reference
from .pagexml import align_documents
from .text import read_text


def _percentage(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from exc
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 100")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocrdiff",
        description="Align noisy Hebrew OCR output against a reference text.",
    )
    parser.add_argument("--version", action="version", version=f"ocrdiff {__version__}")
    parser.add_argument(
        "--home",
        help="Project root holding ref/ (default: $OCRDIFF_HOME, else the package's own root).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    align = subparsers.add_parser("align", help="Align an OCR text file against a reference.")
    align.add_argument("--ocr", required=True, help="Path to the OCR text file.")
    align.add_argument("--ref", required=True, help="Reference name inside ref/, or a path to one.")
    align.add_argument("--out", type=Path, help="Output directory (default: <home>/aligned).")
    align.add_argument("--threshold", type=_percentage, default=70, help="Low-score threshold.")
    align.set_defaults(func=_cmd_align)

    pagexml = subparsers.add_parser("pagexml", help="Align PAGE-XML files against a reference.")
    pagexml.add_argument(
        "--pagexml", required=True, help="A PAGE-XML file, or a directory of them."
    )
    pagexml.add_argument(
        "--ref", required=True, help="Reference name inside ref/, or a path to one."
    )
    pagexml.add_argument("--out", type=Path, help="Output directory (default: <home>/aligned).")
    pagexml.add_argument("--threshold", type=_percentage, default=70, help="Low-score threshold.")
    pagexml.set_defaults(func=_cmd_pagexml)

    serve = subparsers.add_parser("serve", help="Serve the web app and the HTTP API.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8000, help="Bind port (default 8000).")
    serve.add_argument("--reload", action="store_true", help="Reload on source changes (dev only).")
    serve.add_argument("--frontend-dir", type=Path, help="Directory holding the built frontend.")
    serve.set_defaults(func=_cmd_serve)

    return parser


def _output_dir(args: argparse.Namespace, settings: Settings) -> Path:
    return args.out if args.out is not None else settings.output_dir


def _cmd_align(args: argparse.Namespace, settings: Settings) -> int:
    reference = settings.resolve_reference(args.ref)
    content = read_text(Path(args.ocr), max_bytes=settings.max_upload_bytes)
    alignment = align_text(content, reference, threshold=args.threshold)
    paths = alignment.save(_output_dir(args, settings))

    print(format_report(alignment))
    for label, path in sorted(paths.items()):
        print(f"- {label}: {path}")
    return 0


def _cmd_pagexml(args: argparse.Namespace, settings: Settings) -> int:
    reference = settings.resolve_reference(args.ref)
    index = load_reference(reference)
    outcomes, failures = align_documents(
        Path(args.pagexml),
        index,
        out_dir=_output_dir(args, settings),
        threshold=args.threshold,
        limit=settings.max_xml_files,
        max_bytes=settings.max_upload_bytes,
    )

    for outcome in outcomes:
        summary = outcome.alignment.summary
        print(
            f"✓ {outcome.filename}: {summary.lines} lines, average {summary.average_score:.2f}, "
            f"{outcome.updated_lines} lines corrected -> {outcome.xml_path}"
        )
    for failure in failures:
        print(f"✗ {failure.filename}: {failure.message}", file=sys.stderr)

    return 0 if outcomes else 1


def _cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    resolved = settings.with_overrides(frontend_dir=args.frontend_dir)
    if args.reload:
        # --reload spawns a process that rebuilds Settings from the environment.
        os.environ["OCRDIFF_HOME"] = str(resolved.root)
        os.environ["OCRDIFF_REF_DIR"] = str(resolved.ref_dir)
        os.environ["OCRDIFF_OUTPUT_DIR"] = str(resolved.output_dir)
        if resolved.frontend_dir is not None:
            os.environ["OCRDIFF_FRONTEND_DIR"] = str(resolved.frontend_dir)
        uvicorn.run(
            "ocrdiffalign.app:create_app", factory=True, host=args.host, port=args.port, reload=True
        )
    else:
        from .app import create_app

        uvicorn.run(create_app(resolved), host=args.host, port=args.port)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "debug", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    func: Callable[..., int] | None = getattr(args, "func", None)
    if func is None:  # pragma: no cover - argparse enforces a subcommand
        return 2
    try:
        return func(args, Settings.load(root=args.home))
    except OcrDiffError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive Ctrl-C while serving
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
