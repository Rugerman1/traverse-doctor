"""Closure and rule adjustments on traverses small enough to check by hand."""

import math

import pytest

from conftest import make
from traverse_doctor.traverse import compass_rule, compute_closure, shoelace_area, transit_rule

# 200 x 100 ft rectangle run clockwise from the northwest corner P1, starting due east,
# with the south side taped 0.30 ft long. Angles left are the interior angles of a clockwise loop.
RECT = [("P1", "90-00-00", 200.00), ("P2", "90-00-00", 100.00), ("P3", "90-00-00", 200.30), ("P4", "90-00-00", 100.00)]


def rect():
    # East along the north side; a 90 deg angle turned left of the west backsight then heads south.
    return make(RECT, start="N 90 00 00 E", mode="left")


def test_rectangle_latitudes_departures_and_precision():
    cl = compute_closure(rect())
    assert cl.angular_misclosure_sec == pytest.approx(0.0, abs=1e-6)
    assert [round(a, 6) for a in cl.azimuths] == [90.0, 180.0, 270.0, 0.0]
    assert cl.sum_lat == pytest.approx(0.0, abs=1e-9)
    assert cl.sum_dep == pytest.approx(-0.30, abs=1e-9)
    assert cl.perimeter == pytest.approx(600.30)
    assert cl.precision == pytest.approx(600.30 / 0.30)  # 1:2001
    assert cl.misclosure_azimuth == pytest.approx(270.0)  # traverse ends 0.30 ft west of where it started


def test_rectangle_compass_and_transit_corrections_by_hand():
    inp = rect()
    cl = compute_closure(inp)
    comp = compass_rule(cl, inp)
    # compass: departure corrections = +0.30 * d / 600.30
    assert comp.corr_dep == pytest.approx([0.30 * d / 600.30 for d in (200, 100, 200.30, 100)])
    assert comp.coords["P2"] == pytest.approx((5000.0, 5200.0 + 0.30 * 200 / 600.30))
    tr = transit_rule(cl, inp)
    # transit: only the east-west courses have departures, split by their size (sum |dep| = 400.30)
    assert tr.corr_dep == pytest.approx([0.30 * 200 / 400.30, 0.0, 0.30 * 200.30 / 400.30, 0.0], abs=1e-12)
    assert tr.coords["P2"] == pytest.approx((5000.0, 5200.0 + 0.30 * 200 / 400.30))
    for adj in (comp, tr):
        # adjusted lats and deps sum to zero
        assert sum(cl.lats) + sum(adj.corr_lat) == pytest.approx(0.0, abs=1e-12)
        assert sum(cl.deps) + sum(adj.corr_dep) == pytest.approx(0.0, abs=1e-12)


def test_angular_misclosure_is_spread_evenly():
    rows = [("P1", "90-00-05", 100.0), ("P2", "90-00-05", 100.0), ("P3", "90-00-05", 100.0), ("P4", "90-00-05", 100.0)]
    cl = compute_closure(make(rows, start="N 90 00 00 E", mode="left"))
    assert cl.angular_misclosure_sec == pytest.approx(20.0, abs=1e-6)
    assert cl.angle_correction_sec == pytest.approx(-5.0, abs=1e-9)
    assert cl.allowable_angular_sec == pytest.approx(3 * 5 * 2)
    assert all(a == pytest.approx(90.0) for a in cl.balanced_angles)


def test_angle_sum_note_uses_n_minus_2_times_180(example):
    cl = compute_closure(example)
    assert "540°00'00" in cl.sum_theoretical_note
    assert cl.angular_misclosure_sec == pytest.approx(2.0, abs=1e-6)  # 540-00-02 measured


def test_area_by_coordinates():
    assert shoelace_area([(0, 0), (100, 0), (100, 100), (0, 100)]) == pytest.approx(10000)
    # 3-4-5 right triangle
    assert shoelace_area([(0, 0), (0, 4), (3, 0)]) == pytest.approx(6)


def test_example_closes_and_areas_agree(example):
    cl = compute_closure(example)
    assert cl.precision > 50000
    comp = compass_rule(cl, example)
    tr = transit_rule(cl, example)
    assert comp.area == pytest.approx(tr.area, rel=1e-6)
    assert comp.area / 43560 == pytest.approx(17.378, abs=0.001)
    # adjusted course lengths stay within 0.02 ft of the measured ones
    assert all(abs(a - b) < 0.02 for a, b in zip(comp.adj_distances, cl.distances))


def test_azimuth_mode_has_no_angular_closure():
    rows = [("P1", "90", 200.0), ("P2", "0", 100.0), ("P3", "270", 200.3), ("P4", "180", 100.0)]
    cl = compute_closure(make(rows, mode="azimuth"))
    assert cl.angular_misclosure_sec is None
    assert cl.sum_dep == pytest.approx(-0.3)


def test_needs_three_stations():
    with pytest.raises(ValueError):
        compute_closure(make(RECT[:2]))
    assert math.isinf(compute_closure(make([("P1", "60", 10), ("P2", "60", 10), ("P3", "60", 10)],
                                           start="N 90 00 00 E", mode="left")).precision)
