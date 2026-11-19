"""Hand-computed Fosberg values and the daily blend."""

import math
from datetime import date

import pytest

from app.scoring import (
    alert_text,
    band_for,
    dryness_normalized,
    equilibrium_moisture,
    fire_proximity_normalized,
    fosberg_ffwi,
    fosberg_from_moisture,
    moisture_damping,
    proximity_floor,
    score_day,
)


def _manual_ffwi(temp_f: float, rh: float, wind_mph: float) -> float:
    """Independent transcription of the formula, so the test is not a tautology."""
    if rh < 10:
        m = 0.03229 + 0.281073 * rh - 0.000578 * rh * temp_f
    elif rh <= 50:
        m = 2.22749 + 0.160107 * rh - 0.01478 * temp_f
    else:
        m = 21.0606 + 0.005565 * rh ** 2 - 0.00035 * rh * temp_f - 0.483199 * rh
    m = min(30.0, max(0.0, m))
    ratio = m / 30.0
    eta = 1 - 2 * ratio + 1.5 * ratio ** 2 - 0.5 * ratio ** 3
    raw = eta * math.sqrt(1 + wind_mph ** 2) / 0.3002
    return min(100.0, max(0.0, raw))


def test_ffwi_matches_hand_calculation_moderate_afternoon():
    # T = 90 F, RH = 20%, U = 15 mph. Middle EMC branch.
    # m = 2.22749 + 0.160107*20 - 0.01478*90
    #   = 2.22749 + 3.20214 - 1.3302
    #   = 4.09943
    # m/30 = 0.1366476667
    # eta = 1 - 2*(m/30) + 1.5*(m/30)^2 - 0.5*(m/30)^3 = 0.7534377613
    # sqrt(1+225) = 15.033296378
    # FFWI = 0.7534377613 * 15.033296378 / 0.3002 = 37.730357
    result = fosberg_ffwi(90, 20, 15)
    assert result["emc"] == pytest.approx(4.09943, abs=1e-5)
    assert result["eta"] == pytest.approx(0.7534377613, abs=1e-8)
    assert result["ffwi"] == pytest.approx(37.730357, abs=1e-4)
    assert result["ffwi"] == pytest.approx(_manual_ffwi(90, 20, 15))


def test_ffwi_low_humidity_branch_and_high_humidity_branch():
    low = fosberg_ffwi(70, 8, 5)
    assert low["emc"] == pytest.approx(1.957194, abs=1e-5)
    assert low["ffwi"] == pytest.approx(14.875241, abs=1e-4)
    assert low["ffwi"] == pytest.approx(_manual_ffwi(70, 8, 5))

    high = fosberg_ffwi(60, 80, 10)
    assert high["emc"] == pytest.approx(16.34068, abs=1e-5)
    assert high["ffwi"] == pytest.approx(9.201229, abs=1e-4)
    assert high["ffwi"] == pytest.approx(_manual_ffwi(60, 80, 10))


def test_ffwi_caps_at_100_when_raw_exceeds_it():
    # 100 F, 5% RH, 40 mph. Raw index is about 123.
    result = fosberg_ffwi(100, 5, 40)
    assert result["ffwi_raw"] == pytest.approx(123.368841, abs=1e-3)
    assert result["ffwi"] == 100.0


def test_design_point_zero_moisture_and_30_mph_is_about_100():
    # Fosberg scaled the index so EMC 0 and 30 mph land on 100.
    # sqrt(1+900)/0.3002 = 99.9895 because of the 1 inside the square root.
    damped, eta = moisture_damping(0)
    assert damped == 0
    assert eta == pytest.approx(1.0)
    result = fosberg_from_moisture(0, 30)
    assert result["ffwi"] == pytest.approx(math.sqrt(901) / 0.3002, abs=1e-9)
    assert result["ffwi"] == pytest.approx(99.9895, abs=1e-3)


def test_emc_boundaries_use_the_middle_branch_at_10_and_50():
    # Middle branch at RH 10, T 80:
    # 2.22749 + 0.160107*10 - 0.01478*80 = 2.64616
    assert equilibrium_moisture(80, 10) == pytest.approx(2.64616, abs=1e-5)
    # Just below 10 uses the low branch and is not equal to the middle value.
    assert equilibrium_moisture(80, 9.9) != pytest.approx(equilibrium_moisture(80, 10))
    # RH 50 stays on the middle branch; RH 51 uses the high branch.
    at_50 = equilibrium_moisture(85, 50)
    assert at_50 == pytest.approx(2.22749 + 0.160107 * 50 - 0.01478 * 85)
    above = equilibrium_moisture(85, 51)
    high_branch = 21.0606 + 0.005565 * 51**2 - 0.00035 * 51 * 85 - 0.483199 * 51
    assert above == pytest.approx(high_branch)


def test_negative_emc_is_clamped_before_damping():
    clamped, eta = moisture_damping(-5)
    assert clamped == 0
    assert eta == pytest.approx(1.0)
    clamped_high, eta_high = moisture_damping(40)
    assert clamped_high == 30
    assert eta_high == pytest.approx(0.0, abs=1e-12)


def test_rejects_humidity_and_wind_outside_range():
    with pytest.raises(ValueError):
        fosberg_ffwi(70, 101, 5)
    with pytest.raises(ValueError):
        fosberg_ffwi(70, -1, 5)
    with pytest.raises(ValueError):
        fosberg_ffwi(70, 20, -0.1)


def test_dryness_and_fire_ramps():
    assert dryness_normalized(0) == 0
    assert dryness_normalized(21) == 100
    assert dryness_normalized(10.5) == pytest.approx(50)
    assert dryness_normalized(40) == 100
    assert fire_proximity_normalized(5) == 100
    assert fire_proximity_normalized(2) == 100
    assert fire_proximity_normalized(50) == 0
    assert fire_proximity_normalized(80) == 0
    # Halfway from 5 km to 50 km is 27.5 km → 50.
    assert fire_proximity_normalized(27.5) == pytest.approx(50)
    assert fire_proximity_normalized(None) is None


def test_score_renormalizes_when_firms_is_missing():
    # Weights 0.55, 0.25, 0.08 remain (sum 0.88). Nearby fire is omitted.
    # FFWI for 90 F / 20% / 15 mph is 37.730357.
    # Dryness 10.5 days → 50. Red flag on → 100.
    # contribution = 37.730357*(0.55/0.88) + 50*(0.25/0.88) + 100*(0.08/0.88)
    day = score_day(
        weather={"temp_f": 90, "rh": 20, "wind_mph": 15},
        days_since_rain=10.5,
        dryness_note="as of last valid POWER day",
        closest_fire_km=None,
        fire_available=False,
        fire_note="FIRMS_MAP_KEY is not set",
        red_flag=True,
    )
    assert day["partial"] is True
    ffwi = 37.73035698974359
    expected = ffwi * (0.55 / 0.88) + 50 * (0.25 / 0.88) + 100 * (0.08 / 0.88)
    assert day["score_unrounded"] == pytest.approx(expected, abs=0.02)
    assert day["score"] == int(math.floor(expected + 0.5))
    fire = next(item for item in day["breakdown"] if item["key"] == "nearby_fire")
    assert fire["available"] is False
    assert fire["contribution"] is None
    flagged = next(item for item in day["breakdown"] if item["key"] == "red_flag")
    assert flagged["effective_weight"] == pytest.approx(0.08 / 0.88, abs=1e-4)


def test_full_score_uses_nominal_weights_and_bands():
    day = score_day(
        weather={"temp_f": 90, "rh": 20, "wind_mph": 15},
        days_since_rain=21,
        dryness_note="",
        closest_fire_km=27.5,
        fire_available=True,
        fire_note="",
        red_flag=False,
    )
    assert day["partial"] is False
    # 37.730357*0.55 + 100*0.25 + 50*0.12 + 0*0.08
    expected = 37.73035698974359 * 0.55 + 25 + 6
    assert day["score_unrounded"] == pytest.approx(expected, abs=0.02)
    assert day["band"] == band_for(day["score"])
    assert day["band"] in {"Moderate", "High"}


def test_alert_matches_the_saturday_example_and_today():
    today = date(2026, 11, 19)  # Thursday
    saturday = date(2026, 11, 21)
    friday = date(2026, 11, 20)
    sunday = date(2026, 11, 22)
    assert (
        alert_text("High", saturday, today, red_flag=False)
        == "High risk Saturday. Clear brush within 30 ft before Friday."
    )
    assert (
        alert_text("High", today, today, red_flag=False)
        == "High risk today. Clear brush within 30 ft now."
    )
    assert (
        alert_text("Moderate", friday, today, red_flag=False)
        == "Moderate risk Friday. Walk the 5-ft ember zone and the vents before Thursday."
    )
    extreme = alert_text("Extreme", saturday, today, red_flag=True)
    assert extreme.startswith("Extreme risk Saturday.")
    assert "before Friday" in extreme
    assert extreme.endswith("A Red Flag Warning is active.")
    assert (
        alert_text("Low", today, today, False, window_end=sunday)
        == "Low risk through Sunday. Keep the 5-ft zone clear of mulch and debris."
    )
    assert (
        alert_text(
            "Extreme",
            today,
            today,
            False,
            nearby={
                "distance_km": 0.44,
                "bearing": "W",
                "name": "Greene - Caney Creek Lane",
                "kind": "wildfire",
            },
        )
        == "Active wildfire 0.4 km W (Greene - Caney Creek Lane). Extreme risk today. Clear brush within 30 ft now."
    )


def test_proximity_floor_steps_and_overrides_the_weighted_sum():
    assert proximity_floor(0.44) == 85
    assert proximity_floor(2) == 85
    assert proximity_floor(5) == 70
    assert proximity_floor(10) == pytest.approx(35)
    assert proximity_floor(15) == 0
    assert proximity_floor(40) == 0
    assert proximity_floor(None) == 0
    day = score_day(
        weather={"temp_f": 70, "rh": 50, "wind_mph": 5},
        days_since_rain=1,
        dryness_note="",
        closest_fire_km=0.44,
        fire_available=True,
        fire_note="",
        red_flag=False,
    )
    assert day["weighted_sum"] < 70
    assert day["score"] >= 85
    assert day["band"] == "Extreme"
    floor = next(item for item in day["breakdown"] if item["key"] == "proximity_floor")
    assert floor["normalized"] == 85
    assert floor["weight"] == "floor"
    assert "higher of the two" in floor["note"]


def test_bands_on_integer_edges():
    assert band_for(0) == "Low"
    assert band_for(24) == "Low"
    assert band_for(25) == "Moderate"
    assert band_for(49) == "Moderate"
    assert band_for(50) == "High"
    assert band_for(74) == "High"
    assert band_for(75) == "Extreme"
    assert band_for(100) == "Extreme"
