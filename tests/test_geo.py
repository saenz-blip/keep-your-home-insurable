import pytest

from app.geo import bearing_degrees, compass_point, haversine_km, km_to_miles


def test_haversine_known_distance():
    # 1 degree of latitude is about 111.19 km.
    distance = haversine_km(37.0, -122.0, 38.0, -122.0)
    assert distance == pytest.approx(111.19, abs=0.05)


def test_compass_points():
    assert compass_point(37.0, -122.0, 38.0, -122.0) == "N"
    assert compass_point(37.0, -122.0, 36.0, -122.0) == "S"
    assert compass_point(37.0, -122.0, 37.0, -121.0) == "E"
    assert compass_point(37.0, -122.0, 37.0, -123.0) == "W"
    assert compass_point(37.0, -122.0, 38.0, -121.0) == "NE"
    # Due north is 0, not 360, and still "N".
    assert bearing_degrees(37.0, -122.0, 38.0, -122.0) == pytest.approx(0, abs=1e-6)


def test_miles():
    assert km_to_miles(1.609344) == pytest.approx(1.0)
