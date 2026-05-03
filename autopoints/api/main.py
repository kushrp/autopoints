from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from autopoints import __version__
from autopoints.api.models import (
    ProgramsResponse,
    SearchAPIRequest,
    SearchAPIResponse,
    SearchEcho,
)
from autopoints.config import settings
from autopoints.programs.loader import transfer_ratios, valuations
from autopoints.search.build import SUPPORTED_CHART_PROGRAMS, BuildOptions, build_orchestrator
from autopoints.search.models import SearchRequest


def _web_dir() -> Path:
    return Path(str(files("autopoints.web")))


def create_app() -> FastAPI:
    app = FastAPI(title="autopoints", version=__version__)

    web_dir = _web_dir()
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"programs": _programs_payload().model_dump()},
        )

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

    return app


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
