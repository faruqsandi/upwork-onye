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
