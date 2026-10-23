"""The doctor should point at a planted blunder, and stay quiet on a good traverse."""

import pytest

from conftest import EXAMPLE, make
from traverse_doctor.angles import fmt_dms, parse_angle
from traverse_doctor.blunders import diagnose
from traverse_doctor.traverse import compute_closure


def test_clean_traverse_has_no_finding(example):
    f = diagnose(compute_closure(example), example)
    assert f.kind == "none"


@pytest.mark.parametrize("k", range(5))
@pytest.mark.parametrize("error", [1.0, -0.5, 10 / 60])
def test_finds_angle_blunder_at_each_station(k, error):
    rows = list(EXAMPLE)
    name, ang, d = rows[k]
    rows[k] = (name, fmt_dms(parse_angle(ang) + error), d)
    inp = make(rows)
    f = diagnose(compute_closure(inp), inp)
    assert f.kind == "angle" and f.suspect is not None
    assert f.suspect.label == f"Angle at {name}"
    assert f.suspect.correction == pytest.approx(-error * 3600, abs=3)


@pytest.mark.parametrize("k", range(5))
@pytest.mark.parametrize("error", [10.0, -1.0])
def test_finds_distance_blunder_on_each_course(k, error):
    rows = list(EXAMPLE)
    name, ang, d = rows[k]
    rows[k] = (name, ang, d + error)
    inp = make(rows)
    cl = compute_closure(inp)
    f = diagnose(cl, inp)
    assert f.kind == "distance" and f.suspect is not None
    assert f.suspect.label == f"Distance {cl.course_label(k)}"
    assert f.suspect.correction == pytest.approx(-error, abs=0.05)


def test_parallel_courses_are_not_blamed():
    # the two long sides of a rectangle are parallel, so a bad tape on one can't be told from the other
    rows = [("P1", "90-00-00", 200.00), ("P2", "90-00-00", 100.00), ("P3", "90-00-00", 200.30), ("P4", "90-00-00", 100.00)]
    inp = make(rows, start="N 90 00 00 E", mode="left")
    f = diagnose(compute_closure(inp), inp)
    assert f.kind == "distance" and f.suspect is None
