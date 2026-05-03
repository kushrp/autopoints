from datetime import date

import pytest

from autopoints.programs.geo import haversine_miles
from autopoints.providers.static_charts import StaticChartProvider
from autopoints.search.models import Cabin


def test_haversine_jfk_phx_known_distance():
    # JFK -> PHX great-circle is ~2143 statute miles
    d = haversine_miles("JFK", "PHX")
    assert 2100 < d < 2200


def test_haversine_jfk_lax_known_distance():
    # JFK -> LAX is ~2475 statute miles
    d = haversine_miles("JFK", "LAX")
    assert 2400 < d < 2550


async def test_static_chart_aeroplan_jfk_phx_economy():
    provider = StaticChartProvider("AC")
    offers = await provider.search("JFK", "PHX", date(2026, 6, 15), Cabin.economy)
    assert len(offers) == 1
    # JFK->PHX is ~2143 miles, falls in the 1501-2750 bucket -> 12500 points
    assert offers[0].points == 12500
    assert offers[0].provider == "AC"


async def test_static_chart_aeroplan_business():
    provider = StaticChartProvider("AC")
    offers = await provider.search("JFK", "PHX", date(2026, 6, 15), Cabin.business)
    assert len(offers) == 1
    # 1501-2750 bucket business -> 25000
    assert offers[0].points == 25000


def test_haversine_unknown_airport_raises():
    with pytest.raises(KeyError):
        haversine_miles("JFK", "ZZZ")
