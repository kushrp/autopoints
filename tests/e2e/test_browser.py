# Run only this file: pytest -m e2e tests/e2e/test_browser.py
"""Headless Chromium walk-through of the autopoints SPA.

Catches CSS/JS regressions the FastAPI-level pytest suite can't see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def _skip_if_no_browser(exc: Exception) -> None:
    """Convert a missing-browser playwright error into a pytest skip."""
    msg = str(exc)
    if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
        pytest.skip("install browsers: playwright install chromium")
    raise exc


@pytest.fixture
def browser_page(live_server):
    """Yield a fresh Playwright page bound to the live server."""
    try:
        from playwright._impl._errors import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed: pip install -e '.[e2e]'")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PWError as e:
            _skip_if_no_browser(e)
            raise
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        try:
            yield page, live_server
        finally:
            try:
                page.screenshot(path=str(ARTIFACTS / "results.png"), full_page=True)
            except Exception:
                pass
            context.close()
            browser.close()


@pytest.mark.e2e
def test_search_flow_end_to_end(browser_page) -> None:
    page, base = browser_page

    # a) Navigate
    page.goto(f"{base}/", wait_until="domcontentloaded")

    # b) Wait for form to render
    page.wait_for_selector("#search-form", state="visible", timeout=10_000)

    # c) Fill the form (origin/destination/depart_date already have defaults; set them explicitly)
    page.fill("#origin", "JFK")
    page.fill("#destination", "PHX")
    page.fill("#depart_date", "2026-06-15")
    page.fill("#window_days", "2")
    page.select_option("#cabin", "economy")
    page.fill("#passengers", "1")

    # d) Demo checkbox should be on by default
    assert page.is_checked("#demo"), "demo checkbox should default-on"

    # e) Submit
    with page.expect_response(lambda r: "/api/search" in r.url and r.request.method == "POST") as resp_info:
        page.click("#submit-btn")
    resp = resp_info.value
    assert resp.status == 200, f"/api/search returned {resp.status}"

    # f) Results section becomes visible (hidden class removed)
    results = page.locator("#results-section")
    results.wait_for(state="visible", timeout=10_000)
    assert "hidden" not in (results.get_attribute("class") or "")

    # g) At least one row. `wait_for` is strict-mode; use .first to avoid
    # rejection when the demo data yields multiple result rows.
    rows = page.locator("#results-tbody tr.result-row")
    rows.first.wait_for(state="visible", timeout=5_000)
    row_count = rows.count()
    assert row_count >= 1, f"expected >=1 redemption row, got {row_count}"

    # h) Heatmap visible (window_days > 0)
    heatmap = page.locator("#heatmap-section")
    heatmap.wait_for(state="visible", timeout=5_000)
    assert "hidden" not in (heatmap.get_attribute("class") or "")

    # i) At least one heat cell shows a CPP value
    cells = page.locator("#heatmap .heat-cell:not(.empty)")
    assert cells.count() >= 1, "expected at least one populated heatmap cell"
    cell_text = cells.first.inner_text().strip()
    assert "¢" in cell_text, f"heatmap cell should show CPP with ¢ sign, got {cell_text!r}"

    # j) Click first row -> expanded detail row appears
    first_row = rows.first
    first_row.click()
    detail = page.locator("#results-tbody tr.detail-row")
    detail.wait_for(state="visible", timeout=3_000)
    assert detail.count() >= 1, "expected detail row after click"
    assert detail.locator(".detail-block").count() >= 1

    # k) Screenshot (also captured unconditionally in the fixture teardown).
    page.screenshot(path=str(ARTIFACTS / "results.png"), full_page=True)

    # l) Click a sortable header — order should change.
    before = [r.inner_text() for r in rows.all()]
    # Toggle the same column we sort by (effective_cpp) to flip desc -> asc.
    page.click('#results-table thead th[data-sort="effective_cpp"]')
    # Re-query after re-render.
    rows_after = page.locator("#results-tbody tr.result-row")
    # Wait for tbody to settle (re-render is synchronous, but locators re-evaluate).
    page.wait_for_function(
        """([prev]) => {
            const rows = document.querySelectorAll('#results-tbody tr.result-row');
            if (rows.length !== prev.length) return true;
            for (let i = 0; i < rows.length; i++) {
                if (rows[i].innerText !== prev[i]) return true;
            }
            return false;
        }""",
        arg=[before],
        timeout=3_000,
    )
    after = [r.inner_text() for r in rows_after.all()]
    assert after != before, "sort header click should change row order"
    # The indicator class should flip to asc.
    th_class = page.locator('#results-table thead th[data-sort="effective_cpp"]').get_attribute("class") or ""
    assert "sort-asc" in th_class, f"expected sort-asc indicator, got {th_class!r}"
