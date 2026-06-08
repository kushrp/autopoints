"""Minimal Browserbase + Playwright session helper.

NOT a base class. Shared session-creation code only — keeps the AlaskaProvider
(and future direct providers) free of duplicated bootstrap while resisting the
speculative-abstraction trap flagged in the v0 brainstorm's scope review.

Imports are deferred until ``get_session`` is actually called so importing
``autopoints.providers.alaska`` works in environments without browserbase or
playwright installed (the provider raises ``ProviderError`` at invocation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autopoints.config import settings as default_settings
from autopoints.providers.base import ProviderError

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page


async def get_session(
    *,
    settings: Any = None,
    proxy_country: str = "US",
) -> tuple["Page", "Browser"]:
    """Create a Browserbase session and return a Playwright Page over CDP.

    Caller is responsible for closing the returned browser (``await browser.close()``)
    to release the Browserbase session. Returns the existing default page from
    the auto-created context; if more pages are needed, create them via
    ``context.new_page()``.
    """
    s = settings if settings is not None else default_settings
    if not s.browserbase_api_key or not s.browserbase_project_id:
        raise ProviderError(
            "Browserbase not configured. Set BROWSERBASE_API_KEY and "
            "BROWSERBASE_PROJECT_ID in your .env (or environment)."
        )

    try:
        from browserbase import Browserbase
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ProviderError(
            "Browserbase deps not installed. Run `pip install browserbase playwright`."
        ) from e

    bb = Browserbase(api_key=s.browserbase_api_key)
    session = bb.sessions.create(
        project_id=s.browserbase_project_id,
        # Residential proxy + stealth: required for the airline sites these
        # providers target. Geolocated to US so award-search defaults match.
        proxies=[{"type": "browserbase", "geolocation": {"country": proxy_country}}],
        browser_settings={"solveCaptchas": True},
    )

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(session.connect_url)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    return page, browser
