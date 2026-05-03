from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from autopoints.search.models import AwardOffer, Cabin, FlightOffer


class ProviderError(Exception):
    pass


class CashProvider(ABC):
    name: str

    @abstractmethod
    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[FlightOffer]: ...


class AwardProvider(ABC):
    name: str
    program_code: str  # e.g. "AC" for Aeroplan, "BA" for Avios

    @abstractmethod
    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[AwardOffer]: ...
