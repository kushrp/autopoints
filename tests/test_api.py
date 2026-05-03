from fastapi.testclient import TestClient

from autopoints.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_programs():
    r = client.get("/api/programs")
    assert r.status_code == 200
    body = r.json()
    assert "valuations" in body
    assert "transfer_ratios" in body
    assert "supported_charts" in body
    assert body["supported_charts"] == ["AC", "BA", "VS"]
    assert "UR" in body["transfer_ratios"]
    assert body["valuations"]["AC"] > 0
    assert body["cpp_thresholds"]["great"] >= body["cpp_thresholds"]["good"]


def test_search_demo_returns_redemptions():
    r = client.post(
        "/api/search",
        json={
            "origin": "JFK",
            "destination": "PHX",
            "depart_date": "2026-06-15",
            "window_days": 1,
            "cabin": "economy",
            "passengers": 1,
            "demo": True,
            "live_aeroplan": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request"]["origin"] == "JFK"
    assert len(body["redemptions"]) > 0
    assert len(body["cheapest_cash_by_date"]) == 3  # window=1 -> 3 dates
    # Best per (transfer, program) — with 3 currencies × 3 programs we cap at 9.
    assert len(body["redemptions"]) <= 9
    # Each row should have effective_cpp and a verdict.
    for row in body["redemptions"]:
        assert "effective_cpp" in row
        assert row["verdict"] in ("great", "good", "ok", "bad")
    # Sorted desc by effective_cpp
    cpps = [row["effective_cpp"] for row in body["redemptions"]]
    assert cpps == sorted(cpps, reverse=True)


def test_search_validates_iata_length():
    r = client.post(
        "/api/search",
        json={
            "origin": "JFKK",  # too long
            "destination": "PHX",
            "depart_date": "2026-06-15",
            "demo": True,
        },
    )
    assert r.status_code == 422


def test_search_window_clamped():
    r = client.post(
        "/api/search",
        json={
            "origin": "JFK",
            "destination": "PHX",
            "depart_date": "2026-06-15",
            "window_days": 50,  # rejected by validator
            "demo": True,
        },
    )
    assert r.status_code == 422
