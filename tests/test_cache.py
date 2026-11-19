from app.cache import load_feed


def test_simulated_outage_serves_the_cached_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"value": 7}

    live = load_feed("nws", "36.36_-82.80", fetch, outages=set())
    assert live["status"] == "live"
    assert calls["n"] == 1

    cached = load_feed("nws", "36.36_-82.80", fetch, outages={"nws"})
    assert cached["status"] == "cached"
    assert cached["payload"] == {"value": 7}
    assert cached["age_hours"] < 1
    assert "data <1 hour old" in cached["age_label"]
    assert calls["n"] == 1
    assert "simulated outage" in cached["error"]


def test_outage_without_cache_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    missing = load_feed("firms", "36.36_-82.80", lambda: {"no": "call"}, outages={"firms"})
    assert missing["status"] == "unavailable"
    assert missing["payload"] is None
