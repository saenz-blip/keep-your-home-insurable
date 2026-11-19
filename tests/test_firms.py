"""FIRMS parsing and filters. The CSV is a test fixture, not a data file the app loads."""

import pytest

from app.feeds.firms import analyze, parse_csv

HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight"

FIXTURE = f"""{HEADER}
37.9415,-122.3950,320,0.4,0.4,2026-11-19,1200,N,VIIRS,nominal,2,290,0.4,N
38.020,-122.085,330,0.4,0.4,2026-11-19,1210,N20,VIIRS,high,2,300,8.0,D
36.366,-82.800,350,0.4,0.4,2026-11-19,1800,N20,VIIRS,high,2,310,14.6,D
36.50,-83.10,300,0.4,0.4,2026-11-19,1805,N21,VIIRS,low,2,280,2.0,D
39.000,-123.000,310,0.4,0.4,2026-11-19,0100,N,VIIRS,nominal,2,280,0.3,N
39.001,-123.001,311,0.4,0.4,2026-11-19,1400,N21,VIIRS,nominal,2,281,0.4,D
999,-122,1,1,1,2026-11-19,0000,N,VIIRS,nominal,2,1,1,D
"""


def test_filter_refinery_flares_low_confidence_and_persistent_weak_heat():
    result = analyze(
        {"tables": [{"source": "VIIRS_SNPP_NRT", "csv": FIXTURE}], "source_errors": []},
        36.36297,
        -82.79874,
    )
    assert result["dropped_invalid"] == 1
    assert result["raw_count"] == 6
    sites = {row["name"]: row["count"] for row in result["industrial_by_site"]}
    assert sites["Chevron Richmond Refinery"] == 1
    assert sites["Martinez refineries"] == 1
    assert result["low_confidence_count"] == 1
    assert result["possible_static_count"] == 2
    assert result["kept_count"] == 1
    closest = result["closest"]
    assert closest["frp"] == pytest.approx(14.6)
    assert closest["distance_km"] == pytest.approx(0.36, abs=0.05)
    assert closest["bearing"] == "N"
    assert "left out of the score" in result["possible_static"][0]["reason"]


def test_empty_csv_is_no_detections_not_an_error():
    rows, dropped = parse_csv(HEADER + "\n")
    assert rows == []
    assert dropped == 0
    result = analyze(
        {"tables": [{"source": "VIIRS_SNPP_NRT", "csv": HEADER + "\n"}], "source_errors": []},
        36.36,
        -82.80,
    )
    assert result["kept_count"] == 0
    assert result["closest"] is None
    assert any("No active FIRMS" in note for note in result["notes"])


def test_non_csv_body_is_an_error():
    with pytest.raises(ValueError):
        parse_csv("Invalid MAP_KEY")
