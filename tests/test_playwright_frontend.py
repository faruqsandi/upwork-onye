"""Playwright end-to-end frontend integration tests for EHR Media Intelligence dashboard."""

import socket
import threading
import time
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
import uvicorn
from src.api.app import app


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """Starts FastAPI app in a background daemon thread for Playwright tests."""
    port = get_free_port()
    host = "127.0.0.1"
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until server is ready
    base_url = f"http://{host}:{port}"
    import urllib.request

    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("FastAPI live server failed to start within timeout.")

    yield base_url
    server.should_exit = True


@pytest.fixture(scope="module")
def browser_page(live_server):
    """Launches Playwright headless Chromium browser."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(live_server)
        yield page
        browser.close()


class TestDashboardPlaywright:
    """Verifies all UI dashboard interactions via headless Playwright browser."""

    def test_page_load_and_elements(self, browser_page, live_server):
        page = browser_page
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")

        expect(page).to_have_title("EHR Media Intelligence | Clinical Search & FHIR R4")

        # Ingestion button
        btn_reingest = page.locator("#btn-reingest")
        expect(btn_reingest).to_be_visible()
        expect(btn_reingest).to_contain_text("Re-ingest data from directory")

        # Drag and drop area
        drop_zone = page.locator("#drop-zone")
        expect(drop_zone).to_be_visible()
        expect(drop_zone).to_contain_text("Drag & drop clinical records here")

        # Anonymization toggle
        anonymize_btn = page.locator("#anonymize-container")
        expect(anonymize_btn).to_be_visible()
        expect(page.locator("#anonymize-label")).to_have_text("Anonymize PHI")

        # Search bar
        expect(page.locator("#search-input")).to_be_visible()

    def test_semantic_search_and_highlighting(self, browser_page):
        page = browser_page
        search_input = page.locator("#search-input")
        search_input.fill("diabetes neuropathy")
        page.locator("#btn-search-exec").click()

        # Wait for search results
        results_list = page.locator("#results-list")
        expect(results_list).to_be_visible()
        first_card = page.locator(".result-card").first
        expect(first_card).to_be_visible(timeout=5000)

        # Verify query keyword highlighting with <mark> tags
        marks = first_card.locator("mark")
        expect(marks.first).to_be_visible()
        mark_text = marks.first.text_content().lower()
        assert "diabetes" in mark_text or "neuropathy" in mark_text

    def test_patient_drawer_inspection(self, browser_page):
        page = browser_page
        first_card = page.locator(".result-card").first
        first_card.click()

        drawer = page.locator("#patient-drawer")
        expect(drawer).to_be_visible(timeout=5000)

        # Check drawer contents
        expect(page.locator("#drawer-patient-name")).not_to_have_text("Loading...")
        expect(page.locator("#drawer-chief-concern")).to_be_visible()
        expect(page.locator("#drawer-full-narrative")).to_be_visible()

        # Toggle raw FHIR viewer
        page.locator("text=View Raw FHIR R4 Bundle JSON").click()
        raw_fhir = page.locator("#raw-fhir-json")
        expect(raw_fhir).to_be_visible()
        expect(raw_fhir).to_contain_text('"resourceType": "Bundle"')

        # Close drawer
        page.locator("button[aria-label='Close detail panel']").click()
        expect(drawer).to_be_hidden()

    def test_anonymization_toggle(self, browser_page):
        page = browser_page

        # 1. Capture initial real patient name and MRN from first card
        card_name_el = page.locator(".result-card .patient-card-name").first
        initial_name = card_name_el.text_content()
        assert "De-identified" not in initial_name

        card_mrn_el = page.locator(".result-card .patient-card-mrn").first
        initial_mrn = card_mrn_el.text_content()
        assert "MRN:******" not in initial_mrn

        # 2. Toggle Anonymization ON
        page.locator("#anonymize-container").click()
        expect(page.locator("#anonymize-label")).to_have_text("PHI Masked")

        # Verify card presentation is now de-identified
        expect(card_name_el).to_contain_text("De-identified")
        expect(card_mrn_el).to_have_text("MRN:******")

        # 3. Open drawer and check de-identification
        page.locator(".result-card").first.click()
        drawer = page.locator("#patient-drawer")
        expect(drawer).to_be_visible()

        expect(page.locator("#drawer-patient-name")).to_contain_text("De-identified")
        expect(page.locator("#drawer-mrn-badge")).to_have_text("MRN:******")
        expect(page.locator("#drawer-demographics")).to_contain_text("DOB: ")
        expect(page.locator("#drawer-demographics")).to_contain_text("-XX-XX")

        # Check that raw FHIR bundle also masks PHI
        page.locator("text=View Raw FHIR R4 Bundle JSON").click()
        raw_fhir = page.locator("#raw-fhir-json")
        expect(raw_fhir).to_contain_text("DE-IDENTIFIED")
        expect(raw_fhir).to_contain_text("MRN:******")

        # Close drawer
        page.locator("button[aria-label='Close detail panel']").click()
        expect(drawer).to_be_hidden()

        # 4. Toggle Anonymization OFF
        page.locator("#anonymize-container").click()
        expect(page.locator("#anonymize-label")).to_have_text("Anonymize PHI")
        expect(card_name_el).to_have_text(initial_name)
        expect(card_mrn_el).to_have_text(initial_mrn)

    def test_ingestion_telemetry_and_stats(self, browser_page):
        page = browser_page
        btn_reingest = page.locator("#btn-reingest")
        btn_reingest.click()

        # Check telemetry stats panel appears
        stats_panel = page.locator("#ingestion-stats-panel")
        expect(stats_panel).to_be_visible(timeout=10000)

        # Check stats values
        stat_total = page.locator("#stat-total")
        expect(stat_total).not_to_have_text("0")

        stat_successful = page.locator("#stat-successful")
        expect(stat_successful).not_to_have_text("0")

        stat_duplicates = page.locator("#stat-duplicates")
        expect(stat_duplicates).to_be_visible()

        stat_failed = page.locator("#stat-failed")
        expect(stat_failed).to_be_visible()

        stats_message = page.locator("#stats-message")
        expect(stats_message).to_contain_text("Ingestion complete")

        # Dismiss stats panel
        page.locator("text=✕ Dismiss").click()
        expect(stats_panel).to_be_hidden()
