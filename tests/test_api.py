from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_exposes_the_two_example_addresses():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    addresses = [item["address"] for item in body["examples"]]
    assert addresses[0] == "Caney Creek Lane, Greene County, TN"
    assert "Berkeley" in addresses[1]
    assert len(body["checklist"]) == 10


def test_empty_query_is_a_clean_message():
    response = client.get("/api/risk")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "address" in body["message"].lower()


def test_geocoder_miss_does_not_500(monkeypatch):
    monkeypatch.setattr("app.risk.search", lambda query: [])
    response = client.get("/api/risk", params={"address": "not a real place zzzqqq"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "not_found"


def test_ambiguous_geocode_returns_candidates(monkeypatch):
    monkeypatch.setattr(
        "app.risk.search",
        lambda query: [
            {"label": "Springfield, Illinois", "lat": 39.78, "lon": -89.65},
            {"label": "Springfield, Massachusetts", "lat": 42.10, "lon": -72.59},
        ],
    )
    response = client.get("/api/risk", params={"address": "Springfield"})
    assert response.status_code == 200
    body = response.json()
    assert body["error"] == "ambiguous"
    assert len(body["candidates"]) == 2
