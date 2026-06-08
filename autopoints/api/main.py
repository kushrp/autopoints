from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from autopoints import __version__
from autopoints.api import onboard as onboard_mod
from autopoints.api.models import (
    ProgramsResponse,
    SearchAPIRequest,
    SearchAPIResponse,
    SearchEcho,
    WatchlistCreate,
    WatchlistHitView,
    WatchlistRunView,
    WatchlistView,
)
from autopoints.api.onboard import (
    AmadeusTestRequest,
    DiscordTestRequest,
    GenerateRequest,
    GenerateResponse,
    OnboardStatus,
    TestResult,
)
from autopoints.config import settings
from autopoints.programs.loader import transfer_ratios, valuations
from autopoints.search.build import SUPPORTED_CHART_PROGRAMS, BuildOptions, build_orchestrator
from autopoints.search.models import SearchRequest
from autopoints.watchlist_runner import run_all, store_for_settings
from autopoints.watchlists import Watchlist


def _web_dir() -> Path:
    return Path(str(files("autopoints.web")))


def create_app() -> FastAPI:
    app = FastAPI(title="autopoints", version=__version__)

    web_dir = _web_dir()
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/", response_model=None)
    async def index(request: Request) -> HTMLResponse | RedirectResponse:
        if not onboard_mod.is_configured().configured:
            return RedirectResponse(url="/onboard", status_code=307)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"programs": _programs_payload().model_dump()},
        )

    @app.get("/onboard", response_class=HTMLResponse)
    async def onboard_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "onboard.html",
            {"status": onboard_mod.is_configured().model_dump()},
        )

    @app.get("/api/onboard/status", response_model=OnboardStatus)
    async def onboard_status() -> OnboardStatus:
        return onboard_mod.is_configured()

    @app.post("/api/onboard/test/amadeus", response_model=TestResult)
    async def onboard_test_amadeus(req: AmadeusTestRequest) -> TestResult:
        return await onboard_mod.test_amadeus(req)

    @app.post("/api/onboard/test/discord", response_model=TestResult)
    async def onboard_test_discord(req: DiscordTestRequest) -> TestResult:
        return await onboard_mod.test_discord(req)

    @app.post("/api/onboard/generate", response_model=GenerateResponse)
    async def onboard_generate(req: GenerateRequest) -> GenerateResponse:
        return onboard_mod.generate(req)

    @app.post("/api/onboard/complete")
    async def onboard_complete() -> dict:
        onboard_mod.mark_complete()
        return {"ok": True}

    @app.delete("/api/onboard/complete")
    async def onboard_reset() -> dict:
        onboard_mod.unmark_complete()
        return {"ok": True}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/programs", response_model=ProgramsResponse)
    async def programs() -> ProgramsResponse:
        return _programs_payload()

    @app.post("/api/search", response_model=SearchAPIResponse)
    async def search(req: SearchAPIRequest) -> SearchAPIResponse:
        try:
            search_req = SearchRequest(
                origin=req.origin.upper(),
                destination=req.destination.upper(),
                depart_date=req.depart_date,
                window_days=req.window_days,
                cabin=req.cabin,
                passengers=req.passengers,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        built = build_orchestrator(
            BuildOptions(
                demo=req.demo,
                use_live_aeroplan=req.live_aeroplan,
                force_refresh=False,
            )
        )
        outcome = await built.orchestrator.run(search_req)

        cheapest_by_date: dict[str, int] = {}
        for o in outcome.cash_offers:
            d = o.depart_date.isoformat()
            if d not in cheapest_by_date or o.cash_cents < cheapest_by_date[d]:
                cheapest_by_date[d] = o.cash_cents

        return SearchAPIResponse(
            request=SearchEcho(
                origin=search_req.origin,
                destination=search_req.destination,
                depart_date=search_req.depart_date,
                window_days=search_req.window_days,
                cabin=search_req.cabin,
                passengers=search_req.passengers,
            ),
            redemptions=outcome.best_per_program(),
            all_redemptions=outcome.redemptions,
            cheapest_cash_by_date=cheapest_by_date,
            warnings=built.warnings + outcome.warnings,
        )

    @app.get("/api/watchlists", response_model=list[WatchlistView])
    async def list_watchlists() -> list[WatchlistView]:
        return [_watchlist_to_view(w) for w in store_for_settings().list()]

    @app.post("/api/watchlists", response_model=WatchlistView)
    async def create_watchlist(req: WatchlistCreate) -> WatchlistView:
        store = store_for_settings()
        wl = store.add(
            origin=req.origin,
            destination=req.destination,
            depart_date=req.depart_date,
            window_days=req.window_days,
            cabin=req.cabin,
            passengers=req.passengers,
            threshold_cpp=req.threshold_cpp,
            label=req.label,
        )
        return _watchlist_to_view(wl)

    @app.delete("/api/watchlists/{watchlist_id}")
    async def delete_watchlist(watchlist_id: str) -> dict:
        if not store_for_settings().remove(watchlist_id):
            raise HTTPException(status_code=404, detail="not found")
        return {"deleted": watchlist_id}

    @app.post("/api/watchlists/run", response_model=list[WatchlistRunView])
    async def run_watchlists(
        demo: bool = True,
        # live_aeroplan is deprecated 2026-06-07 (endpoint NXDOMAIN). Left in
        # place for phase-2 repair; see autopoints/providers/aeroplan.py.
        live_aeroplan: bool = False,
    ) -> list[WatchlistRunView]:
        store = store_for_settings()
        results = await run_all(store, demo=demo, use_live_aeroplan=live_aeroplan)
        return [
            WatchlistRunView(
                watchlist=_watchlist_to_view(r.watchlist),
                hits=[WatchlistHitView(is_new=h.is_new, redemption=h.redemption) for h in r.hits],
                warnings=r.warnings,
            )
            for r in results
        ]

    return app


def _watchlist_to_view(wl: Watchlist) -> WatchlistView:
    return WatchlistView(
        id=wl.id,
        origin=wl.origin,
        destination=wl.destination,
        depart_date=wl.depart_date,
        window_days=wl.window_days,
        cabin=wl.cabin,
        passengers=wl.passengers,
        threshold_cpp=wl.threshold_cpp,
        label=wl.label,
        created_at=wl.created_at,
        arrive_before_local=wl.arrive_before_local,
    )


def _programs_payload() -> ProgramsResponse:
    return ProgramsResponse(
        valuations=valuations(),
        transfer_ratios=transfer_ratios(),
        supported_charts=list(SUPPORTED_CHART_PROGRAMS),
        cpp_thresholds={
            "great": settings.autopoints_cpp_great,
            "good": settings.autopoints_cpp_good,
        },
    )


app = create_app()
