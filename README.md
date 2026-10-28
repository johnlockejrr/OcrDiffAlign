# OcrDiffAlign

Align noisy Hebrew OCR output against a reference text — as a CLI, an HTTP API and a Svelte web
app. Built for manuscript transcriptions (PAGE-XML from Bodleian / BL / HCL digitisations) checked
against a printed critical edition.

- **Engine** — one implementation of normalisation, fuzzy matching, character diffing and
  confusion counting, shared by every entry point.
- **CLI** — `ocrdiff align` for plain OCR text, `ocrdiff pagexml` for PAGE-XML files,
  `ocrdiff serve` for the app.
- **Web app** — Svelte SPA with reference selection, inline editing of every matched line,
  character-level diffs and CSV/TXT downloads.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.10+; the project pins its own `.venv`)
- Node.js 20+ for the frontend build

## Install

```bash
uv sync --extra dev
```

```bash
npm --prefix frontend install
```

## Run

One command in development — starts the API on `:8000` with autoreload and Vite on `:5173`:

```bash
npm --prefix frontend run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to the FastAPI process, so there
is nothing to configure.

One command for production — builds the SPA and serves the app and the API from a single process
on <http://127.0.0.1:8000>:

```bash
npm --prefix frontend run build && uv run uvicorn ocrdiffalign.app:app --host 127.0.0.1 --port 8000
```

## CLI

```bash
uv run ocrdiff align --ocr samples/ocr.txt --ref schorch_verses.txt --out aligned
```

```bash
uv run ocrdiff pagexml --pagexml samples --ref schorch_verses.txt --out aligned
```

`--ref` accepts a reference name inside `ref/` (`schorch_verses.txt`) or a path to a reference file.
`align` writes `aligned/<ref>-<id>.csv`, `.txt` and `confusions_<ref>-<id>.csv`; `pagexml` writes
corrected documents to `aligned/xml/`. The web app produces the same artefacts as the CLI — both
call this one engine.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness and version |
| `GET` | `/api/refs` | Reference files available for selection |
| `POST` | `/api/align` | Align pasted OCR text; returns results, summary, confusions and artefact contents |
| `POST` | `/api/pagexml` | Align uploaded PAGE-XML files; saves corrected XML, reports per-file errors |
| `POST` | `/api/export` | Persist edited results and re-render the artefacts |
| `GET` | `/api/docs` | OpenAPI explorer |

`POST /api/align` answers with the artefacts inline, so downloads need no second request;
`POST /api/export` exists so an edited review can be saved without re-running the alignment.

## Layout

```
src/ocrdiffalign/
├── text.py       # normalisation, file reading, line splitting
├── diff.py       # character diff + confusion counting
├── index.py      # reference index and candidate lookup
├── align.py      # alignment of lines, artefacts, reporting
├── pagexml.py    # PAGE-XML parsing, correction, serialisation
├── app.py        # FastAPI schemas, routes, error handling
├── cli.py        # `ocrdiff` entry point
└── config.py     # settings resolution and reference validation
frontend/         # Svelte SPA (Vite)
ref/              # reference texts
samples/          # sample PAGE-XML documents for testing
tests/            # pytest suite
aligned/          # generated output (gitignored)
```

## How the alignment works

OCR lines are matched against reference *lines* rather than against every word window in the
reference. Candidates for a line are the reference line itself plus joins with the following line,
which covers an OCR line that spans two verses. Matching is anchored: after line *n* is placed,
line *n+1* is searched in a window around that position, falling back to a global search when the
window scores badly. That is both cheaper than scanning the whole reference per line and more
accurate, because it uses the fact that a page of manuscript follows its edition in order.

Confusions come from `difflib` opcodes on the *normalised* pair, so a multi-character replacement
reports every character involved instead of pairing only the last removed character with the first
added one. Markup is HTML-escaped, so OCR text cannot inject content into the SPA.

## Configuration

All settings are environment variables with working defaults; nothing needs a `.env` file.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OCRDIFF_HOME` | package root | Project root holding `ref/` |
| `OCRDIFF_REF_DIR` | `$OCRDIFF_HOME/ref` | Allowed location of reference files |
| `OCRDIFF_OUTPUT_DIR` | `$OCRDIFF_HOME/aligned` | Where artefacts are written |
| `OCRDIFF_FRONTEND_DIR` | `frontend/dist` if present | Static build served at `/` |
| `OCRDIFF_MAX_UPLOAD_BYTES` | `8388608` | Size cap per file (reference, upload) |
| `OCRDIFF_MAX_OCR_CHARS` | `2000000` | Size cap on a submitted OCR body |
| `OCRDIFF_MAX_XML_FILES` | `64` | Files per request or per CLI run |
| `OCRDIFF_ALLOWED_ORIGINS` | localhost:5173 origins | CORS allowlist |
| `OCRDIFF_DEBUG` | off | Include exception details in 500 responses |

## Security notes

- Reference names are validated against `ref_dir`: no traversal, no absolute paths outside it, no
  symlinks. Upload filenames are reduced to their basename before being written.
- Every payload is size-checked before parsing. XML is parsed with `resolve_entities=False`, so
  entity definitions (including expansion bombs) are never expanded.
- Responses carry `x-content-type-options: nosniff`, `x-frame-options: DENY`,
  `referrer-policy: no-referrer` and `cache-control: no-store`; the SPA also gets a CSP.
- CORS is an explicit allowlist with `allow_credentials=False`, and expected errors return
  `{"error": <code>, "message": <text>}` instead of a traceback.
- There is no authentication: the app is meant to be bound to `127.0.0.1`. Put it behind a
  reverse proxy with auth if you expose it to a network.

## Tests

```bash
uv run pytest
```

The suite covers normalisation, the diff and confusion rules (including the multi-character replace
case), index anchoring and the global fallback, PAGE-XML parsing and write-back against the committed
samples, and the HTTP layer including reference traversal, size limits and validation errors.

## License

MIT — see [LICENSE](LICENSE).
