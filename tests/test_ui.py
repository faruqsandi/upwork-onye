"""Unit tests for Task 5: Frontend UI and API integration."""

from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)


class TestFrontendDashboard:
    def test_serve_index_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "EHR Media Intelligence" in resp.text
        assert "Tailwind CSS" in resp.text or "tailwindcss" in resp.text
        assert "search-input" in resp.text
        assert "drop-zone" in resp.text
        assert "Re-ingest data from directory" in resp.text
        assert "anonymize-container" in resp.text
        assert "toggle-anonymize" in resp.text
        assert "ingestion-stats-panel" in resp.text
        assert "stat-total" in resp.text
        assert "stat-successful" in resp.text
        assert "stat-failed" in resp.text
        assert "stat-duplicates" in resp.text
        assert "btn-clear-data" in resp.text
        assert "Clear Data" in resp.text
        assert "SLA &lt;2000ms" not in resp.text
        assert "SLA <2000ms" not in resp.text

    def test_ingest_telemetry_endpoint(self):
        resp = client.post("/ingest")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_ingested" in data
        assert "successful" in data
        assert "failed" in data
        assert "skipped_duplicates" in data
        assert data["total_ingested"] >= data["successful"]
        assert data["successful"] >= 10

    def test_upload_endpoint_with_single_record_files(self):
        from pathlib import Path
        test_file = Path("data/raw/patient_test.json")
        try:
            json_content = b'{"patient_id": "P-TEST-UP", "first_name": "Upload", "last_name": "Test", "dob": "1990-05-15", "gender": "Female", "mrn": "MRN-TEST-99"}'
            files = [
                ("files", ("patient_test.json", json_content, "application/json")),
            ]
            resp = client.post("/upload", files=files)
            assert resp.status_code == 200
            data = resp.json()
            assert data["files_uploaded"] == 1
            assert data["patients_processed"] >= 1
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_static_assets_served(self):
        resp_css = client.get("/static/css/style.css")
        assert resp_css.status_code == 200

        resp_js = client.get("/static/js/app.js")
        assert resp_js.status_code == 200
        assert "executeSearch" in resp_js.text

    def test_patient_list_and_detail_endpoints(self):
        resp = client.get("/patients")
        assert resp.status_code == 200
        patients = resp.json()
        assert len(patients) >= 10

        p1_id = patients[0]["patient_id"]
        detail_resp = client.get(f"/patients/{p1_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert "summary" in detail
        assert "chief_concern" in detail["summary"]
        assert "audit_log" in detail

    def test_fhir_bundle_endpoint(self):
        resp = client.get("/patients")
        p1_id = resp.json()[0]["patient_id"]

        bundle_resp = client.get(f"/bundles/{p1_id}")
        assert bundle_resp.status_code == 200
        bundle = bundle_resp.json()
        assert bundle.get("resourceType") == "Bundle"
        assert len(bundle.get("entry", [])) >= 1

