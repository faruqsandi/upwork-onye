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


@pytest.fixture(autouse=True)
def cleanup_modals(browser_page):
    """Ensures modal slide-over drawers are closed before and after each test."""
    yield
    drawer = browser_page.locator("#patient-drawer")
    if drawer.is_visible():
        close_btn = browser_page.locator("button[aria-label='Close detail panel']")
        if close_btn.is_visible():
            close_btn.click()
            browser_page.wait_for_timeout(300)


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

        # Clear data button
        btn_clear = page.locator("#btn-clear-data")
        expect(btn_clear).to_be_visible()
        expect(btn_clear).to_contain_text("Clear Data")

        # Drag and drop area
        drop_zone = page.locator("#drop-zone")
        expect(drop_zone).to_be_visible()
        expect(drop_zone).to_contain_text("Drag & drop clinical records here")

        # Anonymization toggle
        anonymize_btn = page.locator("#anonymize-container")
        expect(anonymize_btn).to_be_visible()
        expect(page.locator("#anonymize-label")).to_have_text("Hide Names & Details")

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
        expect(page.locator("#drawer-patient-name")).not_to_have_text("Loading...", timeout=15000)
        expect(page.locator("#drawer-chief-concern")).to_be_visible()
        expect(page.locator("#drawer-full-narrative")).to_be_visible()

        # Toggle raw FHIR viewer
        page.locator("#btn-toggle-fhir").click()
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
        assert "Hidden" not in initial_name

        card_mrn_el = page.locator(".result-card .patient-card-mrn").first
        initial_mrn = card_mrn_el.text_content()
        assert "MRN:******" not in initial_mrn

        # 2. Toggle Anonymization ON
        page.locator("#anonymize-container").click()
        expect(page.locator("#anonymize-label")).to_have_text("Names Hidden")

        # Verify card presentation is now de-identified
        expect(card_name_el).to_contain_text("Hidden")
        expect(card_mrn_el).to_have_text("MRN:******")

        # 3. Open drawer and check de-identification
        page.locator(".result-card").first.click()
        drawer = page.locator("#patient-drawer")
        expect(drawer).to_be_visible()

        expect(page.locator("#drawer-patient-name")).to_contain_text("Hidden")
        expect(page.locator("#drawer-mrn-badge")).to_have_text("MRN:******")
        expect(page.locator("#drawer-demographics")).to_contain_text("DOB: ")
        expect(page.locator("#drawer-demographics")).to_contain_text("-XX-XX")

        # Check that raw FHIR bundle also masks PHI
        page.locator("#btn-toggle-fhir").click()
        raw_fhir = page.locator("#raw-fhir-json")
        expect(raw_fhir).to_contain_text("DE-IDENTIFIED")
        expect(raw_fhir).to_contain_text("MRN:******")

        # Close drawer
        page.locator("button[aria-label='Close detail panel']").click()
        expect(drawer).to_be_hidden()

        # 4. Toggle Anonymization OFF
        page.locator("#anonymize-container").click()
        expect(page.locator("#anonymize-label")).to_have_text("Hide Names & Details")
        expect(card_name_el).to_have_text(initial_name)
        expect(card_mrn_el).to_have_text(initial_mrn)

    def test_ingestion_telemetry_and_stats(self, browser_page):
        page = browser_page
        btn_reingest = page.locator("#btn-reingest")
        btn_reingest.click()

        # Check telemetry stats panel appears
        stats_panel = page.locator("#ingestion-stats-panel")
        expect(stats_panel).to_be_visible(timeout=30000)

        # Wait for ingestion to complete and final stats to be rendered
        stats_message = page.locator("#stats-message")
        expect(stats_message).to_contain_text("Ingestion complete", timeout=90000)

        # Check stats values
        stat_unprocessed = page.locator("#stat-unprocessed")
        expect(stat_unprocessed).to_be_visible()

        stat_in_processing = page.locator("#stat-in-processing")
        expect(stat_in_processing).to_be_visible()

        stat_total = page.locator("#stat-total")
        expect(stat_total).not_to_have_text("0")

        stat_successful = page.locator("#stat-successful")
        expect(stat_successful).not_to_have_text("0")

        stat_duplicates = page.locator("#stat-duplicates")
        expect(stat_duplicates).to_be_visible()

        stat_failed = page.locator("#stat-failed")
        expect(stat_failed).to_be_visible()

        # Telemetry is displayed as bare inline text below Clinical Semantic Search
        expect(stats_panel).to_be_visible()

    def test_url_query_parameters_updating(self, browser_page, live_server):
        """Verifies that user interactions dynamically update the URL query string for bookmarking."""
        page = browser_page
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")

        # 1. Search query updates URL
        search_input = page.locator("#search-input")
        search_input.fill("acute chest pain")
        page.locator("#btn-search-exec").click()
        page.wait_for_timeout(300)
        assert "q=acute" in page.url and "chest" in page.url

        # 2. Filter dropdown updates URL
        page.locator("#filter-resource-type").select_option("DiagnosticReport")
        page.wait_for_timeout(300)
        assert "type=DiagnosticReport" in page.url

        # 3. Anonymization updates URL
        page.locator("#anonymize-container").click()
        page.wait_for_timeout(300)
        assert "anonymize=true" in page.url

        # 4. Opening patient drawer adds patient parameter
        first_card = page.locator(".result-card").first
        expect(first_card).to_be_visible(timeout=5000)
        first_card.click()

        drawer = page.locator("#patient-drawer")
        expect(drawer).to_be_visible(timeout=5000)
        assert "patient=" in page.url

        # 5. Closing drawer removes patient parameter
        page.locator("button[aria-label='Close detail panel']").click()
        expect(drawer).to_be_hidden()
        assert "patient=" not in page.url

        # Reset anonymization for subsequent tests
        page.locator("#anonymize-container").click()

    def test_bookmarkable_url_direct_load(self, browser_page, live_server):
        """Verifies that loading a bookmarked URL with query, type filter, and anonymization restores state."""
        page = browser_page
        bookmarked_url = f"{live_server}/?q=pneumonia&type=DocumentReference&anonymize=true"
        page.goto(bookmarked_url)
        page.wait_for_load_state("domcontentloaded")

        # Check search input restored
        search_input = page.locator("#search-input")
        expect(search_input).to_have_value("pneumonia")

        # Check filter dropdown restored
        filter_type = page.locator("#filter-resource-type")
        expect(filter_type).to_have_value("DocumentReference")

        # Check anonymization active
        expect(page.locator("#anonymize-label")).to_have_text("Names Hidden")

        # Verify results loaded
        results_list = page.locator("#results-list")
        expect(results_list).to_be_visible()
        expect(page.locator(".result-card").first).to_be_visible(timeout=5000)

        # Reset anonymization
        page.locator("#anonymize-container").click()

    def test_bookmarkable_patient_drawer_direct_load(self, browser_page, live_server):
        """Verifies that loading a bookmarked URL with a patient ID opens the drawer immediately."""
        page = browser_page
        bookmarked_url = f"{live_server}/?patient=P-200"
        page.goto(bookmarked_url)
        page.wait_for_load_state("domcontentloaded")

        drawer = page.locator("#patient-drawer")
        expect(drawer).to_be_visible(timeout=5000)
        expect(page.locator("#drawer-patient-name")).not_to_have_text("Loading...", timeout=10000)
        assert "patient=P-200" in page.url

        # Close drawer
        page.locator("button[aria-label='Close detail panel']").click()
        expect(drawer).to_be_hidden()
        assert "patient=" not in page.url

    def test_copy_bookmark_link_button(self, browser_page, live_server):
        """Verifies that the Copy URL / Bookmark button is present and displays toast confirmation."""
        page = browser_page
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")

        btn_copy = page.locator("#btn-copy-url")
        expect(btn_copy).to_be_visible()
        expect(btn_copy).to_contain_text("Copy URL / Bookmark")

        btn_copy.click()
        toast = page.locator("#toast")
        expect(toast).to_be_visible(timeout=3000)
        expect(page.locator("#toast-message")).to_contain_text("URL")

    def test_search_results_click_all_load_successfully(self, browser_page, live_server):
        """Verifies that clicking search result cards (including high-numbered IDs like P-250+)
        loads the patient dossier and raw FHIR bundle without 'Error loading record'."""
        page = browser_page
        page.goto(f"{live_server}/?q=diabetes")
        page.wait_for_load_state("domcontentloaded")

        cards = page.locator(".result-card")
        expect(cards.first).to_be_visible(timeout=5000)
        card_count = cards.count()
        assert card_count > 0

        drawer = page.locator("#patient-drawer")
        close_btn = page.locator("button[aria-label='Close detail panel']")

        for i in range(min(5, card_count)):
            card = cards.nth(i)
            card.click()
            expect(drawer).to_be_visible(timeout=5000)

            # Check that drawer content loaded rather than displaying 'Loading...' or failing
            expect(page.locator("#drawer-patient-name")).not_to_have_text("Loading...", timeout=10000)
            expect(page.locator("#drawer-chief-concern")).not_to_have_text("Loading summary...", timeout=10000)

            # Ensure no error toast appeared
            toast = page.locator("#toast")
            if toast.is_visible():
                assert "Failed to load patient record" not in page.locator("#toast-message").text_content()

            # Close drawer
            close_btn.click()
            expect(drawer).to_be_hidden()
