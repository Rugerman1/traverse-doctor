"""Least squares: exact data, optimality, statistics, and agreement with the compass rule."""

import numpy as np
import pytest

from conftest import EXAMPLE, exact_from_coords, make
from traverse_doctor.angles import RHO, azimuth, wrap180
from traverse_doctor.lsq import adjust, chi2_bounds
from traverse_doctor.model import Station, TraverseInput
from traverse_doctor.traverse import compass_rule, compute_closure

SITE = [(5000.0, 5000.0), (4581.92, 5486.41), (4890.33, 6120.55), (5512.08, 5904.37), (5633.70, 5287.64)]


@pytest.mark.parametrize("mode", ["right", "left"])
def test_exact_data_gives_exact_coordinates(mode):
    pts = SITE if mode == "right" else [(n, 10000 - e) for n, e in SITE]  # mirror runs clockwise
    rows, start = exact_from_coords(pts, mode)
    inp = TraverseInput([Station(n, a, d) for n, a, d in rows], start_n=pts[0][0], start_e=pts[0][1],
                        start_azimuth=start, angle_mode=mode)
    ls = adjust(compute_closure(inp), inp)
    for k, (n, e) in enumerate(pts):
        assert ls.adjustment.coords[f"P{k + 1}"] == pytest.approx((n, e), abs=1e-6)
    assert all(abs(o.residual) < 1e-5 for o in ls.observations)
    assert ls.reference_variance == pytest.approx(0.0, abs=1e-8)


def test_redundancy_is_three_for_angle_traverse_and_two_for_azimuths(example):
    assert adjust(compute_closure(example), example).redundancy == 3
    az_rows = [("P1", "90", 200.0), ("P2", "180", 100.0), ("P3", "270", 200.3), ("P4", "0", 100.0)]
    inp = make(az_rows, mode="azimuth")
    assert adjust(compute_closure(inp), inp).redundancy == 2


def _vtpv(inp, coords):
    """Weighted sum of squared residuals for a set of coordinates, computed independently."""
    names = [s.name for s in inp.stations]
    n = len(names)
    xy = [coords[k] for k in names]
    total = 0.0
    az = lambda i, j: azimuth(xy[j][1] - xy[i][1], xy[j][0] - xy[i][0])  # noqa: E731
    total += (wrap180(az(0, 1) - inp.start_azimuth) * 3600 / 0.001) ** 2
    for i, s in enumerate(inp.stations):
        ang = (az(i, (i + 1) % n) - az(i, (i - 1) % n)) % 360
        total += (wrap180(ang - s.angle) * 3600 / inp.sigma_angle_sec) ** 2
        d = float(np.hypot(*np.subtract(xy[(i + 1) % n], xy[i])))
        total += ((d - s.distance) / inp.sigma_distance(s.distance)) ** 2
    return total


def test_solution_minimizes_weighted_residuals(example):
    ls = adjust(compute_closure(example), example)
    best = ls.adjustment.coords
    base = _vtpv(example, best)
    assert base == pytest.approx(ls.reference_variance * ls.redundancy, rel=1e-4)
    rng = np.random.default_rng(1)
    for _ in range(40):
        moved = {k: (n + rng.normal(0, 0.003), e + rng.normal(0, 0.003)) if k != "A" else (n, e)
                 for k, (n, e) in best.items()}
        assert _vtpv(example, moved) > base


def test_example_statistics_and_compass_agreement(example):
    cl = compute_closure(example)
    ls = adjust(cl, example)
    assert ls.chi2_passes
    assert not ls.flagged
    comp = compass_rule(cl, example)
    for k in comp.coords:
        assert np.hypot(*np.subtract(ls.adjustment.coords[k], comp.coords[k])) < 0.02
    # local redundancy numbers sum to the redundancy
    assert sum(o.redundancy for o in ls.observations) == pytest.approx(ls.redundancy, abs=1e-6)
    assert ls.ellipses[0].semi_major == 0.0 and all(e.semi_major >= e.semi_minor for e in ls.ellipses)


def test_rectangle_splits_the_east_west_error_symmetrically():
    rows = [("P1", "90-00-00", 200.00), ("P2", "90-00-00", 100.00), ("P3", "90-00-00", 200.30), ("P4", "90-00-00", 100.00)]
    inp = make(rows, start="N 90 00 00 E", mode="left")
    ls = adjust(compute_closure(inp), inp)
    res = {o.label: o.residual for o in ls.observations}
    # the long sides share the 0.30 ft, and the angles take a little of it by leaning the short sides
    assert res["Distance P1-P2"] == pytest.approx(-res["Distance P3-P4"], abs=1e-5)  # ppm weights differ slightly
    assert 0.12 < res["Distance P1-P2"] < 0.15
    assert abs(res["Distance P2-P3"]) < 1e-4 and abs(res["Distance P4-P1"]) < 1e-4
    assert res["Angle at P1"] == pytest.approx(res["Angle at P2"], abs=1e-3)
    assert res["Angle at P3"] == pytest.approx(-res["Angle at P1"], abs=1e-3)
    assert ls.chi2_passes is False  # 0.30 ft on 200 ft courses is far beyond a 0.01 ft distance sigma


def test_chi_square_table():
    assert chi2_bounds(3) == (0.216, 9.348)
    lo, hi = chi2_bounds(20)
    assert lo == pytest.approx(9.591, abs=0.05) and hi == pytest.approx(34.170, abs=0.1)


def test_rho():
    assert RHO == pytest.approx(206264.806, abs=1e-3)


def test_angle_blunder_shows_up_in_standardized_residuals():
    rows = list(EXAMPLE)
    rows[2] = ("C", "96-47-44", 658.26)  # 2 minutes off
    inp = make(rows)
    ls = adjust(compute_closure(inp), inp)
    assert not ls.chi2_passes
    assert ls.flagged
