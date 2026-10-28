from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ocrdiffalign.app import create_app
from ocrdiffalign.config import Settings

REF_NAME = "schorch_verses.txt"


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_openapi_is_served_under_the_api_prefix(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200


def test_refs_lists_reference_files_with_sizes(client: TestClient, settings: Settings) -> None:
    entries = client.get("/api/refs").json()["refs"]
    by_name = {entry["name"]: entry["size_bytes"] for entry in entries}
    assert REF_NAME in by_name
    assert by_name[REF_NAME] == (settings.ref_dir / REF_NAME).stat().st_size


def test_root_serves_a_hint_when_the_frontend_is_not_built(client: TestClient) -> None:
    assert client.get("/").json()["frontend"] == "not built"


def test_security_headers_are_on_every_response(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in response.headers  # JSON payloads need no CSP


def test_align_returns_results_summary_and_artefacts(
    client: TestClient, settings: Settings, ocr_sample: str
) -> None:
    response = client.post(
        "/api/align", json={"ref": REF_NAME, "ocr_text": ocr_sample, "threshold": 70}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["lines"] > 0
    assert body["files"]["csv"].startswith("Line No,OCR Line,")
    assert Path(body["paths"]["csv"]).read_text(encoding="utf-8") == body["files"]["csv"]
    assert len(list(settings.output_dir.iterdir())) == 3


def test_align_rejects_an_unknown_reference(client: TestClient) -> None:
    response = client.post("/api/align", json={"ref": "never_written.txt", "ocr_text": "ברא"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_reference"


def test_align_refuses_a_path_reaching_outside_the_reference_dir(client: TestClient) -> None:
    """``../samples/ocr.txt`` exists, so a plain ``open()`` would have read it."""
    response = client.post("/api/align", json={"ref": "../samples/ocr.txt", "ocr_text": "ברא"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_reference"


def test_align_rejects_an_out_of_range_threshold(client: TestClient, ocr_sample: str) -> None:
    response = client.post(
        "/api/align", json={"ref": REF_NAME, "ocr_text": ocr_sample, "threshold": 101}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_align_rejects_an_unknown_field(client: TestClient) -> None:
    response = client.post(
        "/api/align", json={"ref": REF_NAME, "ocr_text": "ברא", "thresholdt": 70}
    )
    assert response.status_code == 422


def test_align_rejects_an_oversized_ocr_body(settings: Settings, ocr_sample: str) -> None:
    client = TestClient(create_app(settings.with_overrides(max_ocr_chars=10)))
    response = client.post("/api/align", json={"ref": REF_NAME, "ocr_text": ocr_sample})
    assert response.status_code == 413
    assert response.json()["error"] == "file_too_large"


def test_align_never_leaks_a_traceback_in_an_error_body(client: TestClient) -> None:
    response = client.post("/api/align", json={"ref": "nope.txt", "ocr_text": "ברא"})
    assert "Traceback" not in response.text


def test_export_persists_edited_results(
    client: TestClient, settings: Settings, ocr_sample: str
) -> None:
    aligned = client.post("/api/align", json={"ref": REF_NAME, "ocr_text": ocr_sample}).json()
    results = aligned["results"]
    results[0]["final_match"] = "מקור מתוקן"

    response = client.post(
        "/api/export",
        json={"ref": REF_NAME, "results": results, "confusions": aligned["confusions"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["txt"].splitlines()[0] == "מקור מתוקן"
    assert Path(body["txt_path"]).read_text(encoding="utf-8").splitlines()[0] == "מקור מתוקן"
    assert len(list(settings.output_dir.iterdir())) == 6


def test_export_rejects_an_empty_result_set(client: TestClient) -> None:
    assert client.post("/api/export", json={"ref": REF_NAME, "results": []}).status_code == 422


def test_pagexml_aligns_uploads_and_saves_xml(
    client: TestClient, settings: Settings, xml_samples: list[Path]
) -> None:
    source = xml_samples[0]
    response = client.post(
        "/api/pagexml",
        data={"ref": REF_NAME, "threshold": "70"},
        files=[("files", (source.name, source.read_bytes(), "application/xml"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert [document["filename"] for document in body["documents"]] == [source.name]
    assert body["errors"] == []
    assert Path(body["documents"][0]["xml_path"]).exists()
    assert (settings.output_dir / "xml" / source.name).exists()


def test_pagexml_collects_per_file_errors_without_failing_the_request(client: TestClient) -> None:
    body = client.post(
        "/api/pagexml",
        data={"ref": REF_NAME},
        files=[("files", ("broken.xml", b"<PcGts", "application/xml"))],
    ).json()
    assert body["documents"] == []
    assert body["errors"][0]["filename"] == "broken.xml"


def test_pagexml_rejects_a_non_xml_upload(client: TestClient) -> None:
    body = client.post(
        "/api/pagexml",
        data={"ref": REF_NAME},
        files=[("files", ("notes.txt", b"not xml at all", "text/plain"))],
    ).json()
    assert body["errors"][0]["filename"] == "notes.txt"


def test_pagexml_requires_a_known_reference(client: TestClient) -> None:
    response = client.post(
        "/api/pagexml", data={"ref": "nope.txt"}, files=[("files", ("a.xml", b"<PcGts/>", ""))]
    )
    assert response.status_code == 400


def test_pagexml_enforces_the_upload_count_limit(
    settings: Settings, xml_samples: list[Path]
) -> None:
    client = TestClient(create_app(settings.with_overrides(max_xml_files=1)))
    response = client.post(
        "/api/pagexml",
        data={"ref": REF_NAME},
        files=[
            ("files", (path.name, path.read_bytes(), "application/xml")) for path in xml_samples[:2]
        ],
    )
    assert response.status_code == 413
