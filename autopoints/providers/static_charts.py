from __future__ import annotations

from datetime import date

from autopoints.programs.geo import haversine_miles
from autopoints.programs.loader import award_chart
from autopoints.providers.base import AwardProvider, ProviderError
from autopoints.search.models import AwardOffer, Cabin


class StaticChartProvider(AwardProvider):
    """Returns chart-floor pricing for distance-based programs.

    This does NOT confirm actual award availability. Use it as a reference
    floor: 'if a saver seat exists, this is what it will cost.' The Aeroplan
    chart in particular publishes its saver bucket as a floor; dynamic
    pricing can run higher.
    """

    name = "static_chart"

    def __init__(self, program_code: str):
        self.program_code = program_code
        # Verify the chart exists for this program.
        try:
            self._chart = award_chart(program_code)
        except FileNotFoundError as e:
            raise ProviderError(f"No award chart available for {program_code}") from e

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        cabin: Cabin,
        passengers: int = 1,
    ) -> list[AwardOffer]:
        distance = haversine_miles(origin, destination)
        region = self._region_for(origin, destination)
        buckets = self._chart.get(region, {}).get(cabin.value)
        if not buckets:
            return []
        points_each = _bucket_lookup(buckets, distance)
        if points_each is None:
            return []
        return [
            AwardOffer(
                provider=self.program_code,
                operating_carrier="**",  # unknown — chart-based, partner-agnostic
                origin=origin.upper(),
                destination=destination.upper(),
                depart_date=depart_date,
                cabin=cabin,
                points=points_each * passengers,
                taxes_cents=560,  # ~$5.60 typical US domestic; provider-specific override later
                fare_class=None,
                stops=0,
            )
        ]

    def _region_for(self, origin: str, destination: str) -> str:
        # Aeroplan chart only has 'within_north_america' encoded for now.
        # Extend when adding international regions.
        from autopoints.programs.geo import airport

        a, b = airport(origin), airport(destination)
        na = {"US", "CA", "MX"}
        if a and b and a["country"] in na and b["country"] in na:
            return "within_north_america"
        return "between_regions"


def _bucket_lookup(buckets: list[dict], distance: float) -> int | None:
    for bucket in buckets:
        if distance <= bucket["max_distance"]:
            return int(bucket["points"])
    return None
