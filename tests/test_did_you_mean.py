from app.feeds.nominatim import did_you_mean


def test_multiple_nominatim_hits_ask_for_confirmation():
    assert did_you_mean("Springfield", "Springfield", 3) is True


def test_missing_city_asks_even_when_there_is_one_hit():
    assert did_you_mean("Caney Creek Lane", "Mosheim", 1) is True


def test_typed_city_is_enough():
    assert did_you_mean("Grizzly Peak Blvd, Berkeley, CA", "Berkeley", 1) is False


def test_city_match_ignores_case_and_spacing():
    assert did_you_mean("  berkeley hills ", "Berkeley", 1) is False


def test_no_locality_and_one_hit_stays_quiet():
    assert did_you_mean("1 Market St", "", 1) is False
