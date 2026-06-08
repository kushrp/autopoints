from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from autopoints.search.models import Cabin, RedemptionResult


class SearchAPIRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    window_days: int = Field(default=0, ge=0, le=7)
    cabin: Cabin = Cabin.economy
    passengers: int = Field(default=1, ge=1, le=9)
    demo: bool = True
    live_aeroplan: bool = Field(
        default=False,
        description="(deprecated 2026-06-07) Hit Aeroplan's live award-search "
        "endpoint. The endpoint hostname returns NXDOMAIN; the flag is left in "
        "place for phase-2 repair.",
    )


class SearchEcho(BaseModel):
    origin: str
    destination: str
    depart_date: date
    window_days: int
    cabin: Cabin
    passengers: int


class SearchAPIResponse(BaseModel):
    request: SearchEcho
    redemptions: list[RedemptionResult]
    all_redemptions: list[RedemptionResult]
    cheapest_cash_by_date: dict[str, int]
    warnings: list[str]


class ProgramsResponse(BaseModel):
    valuations: dict[str, float]
    transfer_ratios: dict[str, dict[str, float]]
    supported_charts: list[str]
    cpp_thresholds: dict[str, float]


class WatchlistCreate(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    window_days: int = Field(default=3, ge=0, le=7)
    cabin: Cabin = Cabin.economy
    passengers: int = Field(default=1, ge=1, le=9)
    threshold_cpp: float = Field(default=1.8, ge=0.0, le=10.0)
    label: str | None = None


class WatchlistView(BaseModel):
    id: str
    origin: str
    destination: str
    depart_date: date
    window_days: int
    cabin: Cabin
    passengers: int
    threshold_cpp: float
    label: str | None
    created_at: float


class WatchlistHitView(BaseModel):
    is_new: bool
    redemption: RedemptionResult


class WatchlistRunView(BaseModel):
    watchlist: WatchlistView
    hits: list[WatchlistHitView]
    warnings: list[str]
