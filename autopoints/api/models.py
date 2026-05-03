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
    live_aeroplan: bool = False


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
