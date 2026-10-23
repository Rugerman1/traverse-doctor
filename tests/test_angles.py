import pytest

from traverse_doctor.angles import fmt_azimuth, fmt_bearing, fmt_dms, parse_angle, parse_direction, wrap180


@pytest.mark.parametrize("text", ["101-24-30", "101 24 30", "101°24'30\"", "101d24m30s", "101.408333333"])
def test_parse_angle_forms(text):
    assert parse_angle(text) == pytest.approx(101 + 24 / 60 + 30 / 3600, abs=1e-8)


@pytest.mark.parametrize("text,az", [
    ("N 26 10 30 E", 26.175), ("S 45 E", 135.0), ("S 45-00-00 W", 225.0), ("N 89 59 59 W", 270 + 1 / 3600),
    ("S49-19-13E", 180 - (49 + 19 / 60 + 13 / 3600)), ("130-40-47", 130 + 40 / 60 + 47 / 3600),
])
def test_parse_direction(text, az):
    assert parse_direction(text) == pytest.approx(az, abs=1e-9)


def test_bearing_round_trip():
    for az in (0.5, 89.9, 90.1, 179.0, 181.0, 269.5, 271.0, 359.5):
        assert parse_direction(fmt_bearing(az, 2)) == pytest.approx(az, abs=1e-5)


def test_formatting():
    assert fmt_dms(101.40833333333) == "101°24'30\""
    assert fmt_bearing(206.175) == "S 26°10'30\" W"
    assert fmt_azimuth(359.9999999) == "0°00'00\""
    assert wrap180(359.0) == -1.0 and wrap180(181) == -179.0


def test_bad_angles_are_rejected():
    with pytest.raises(ValueError):
        parse_angle("12-75-00")
    with pytest.raises(ValueError):
        parse_angle("abc")
