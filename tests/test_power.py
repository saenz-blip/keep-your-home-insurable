from datetime import date

from app.feeds.power import summarize


def test_all_fill_values_are_dropped_and_not_scored():
    days = {f"202611{day:02d}": -999.0 for day in range(1, 20)}
    payload = {"properties": {"parameter": {"PRECTOTCORR": days, "RH2M": {"20261101": 150}}}}
    result = summarize(payload, date(2026, 11, 19))
    assert result["available"] is False
    assert result["days_since_rain"] is None
    assert result["dropped"] >= 19
    assert any("POWER data runs ~3 days behind" in note for note in result["notes"])
    assert any("unusable" in note for note in result["notes"])


def test_days_since_meaningful_rain_stops_at_the_last_valid_day():
    precip = {
        "20261113": 12.0,
        "20261114": 0.1,
        "20261115": 0.0,
        "20261116": 1.0,
        "20261117": -999,
        "20261118": -999,
        "20261119": -999,
    }
    result = summarize({"properties": {"parameter": {"PRECTOTCORR": precip}}}, date(2026, 11, 19))
    assert result["available"] is True
    assert result["days_since_rain"] == 3
    assert result["last_valid"] == "2026-11-16"
    assert result["last_rain"] == "2026-11-13"
    assert result["lag_days"] == 3
    assert any("Dropped 3 POWER fill" in note for note in result["notes"])
