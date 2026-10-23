import math

import pytest

from traverse_doctor.angles import azimuth, parse_angle, parse_direction
from traverse_doctor.model import Station, TraverseInput

EXAMPLE = [("A", "106-15-57", 641.40), ("B", "113-23-03", 705.16), ("C", "96-45-44", 658.26),
           ("D", "120-19-45", 628.61), ("E", "103-15-33", 695.93)]


def make(rows, start="S 49 19 13 E", mode="right", **kw):
    return TraverseInput([Station(n, parse_angle(a), d) for n, a, d in rows],
                         start_azimuth=parse_direction(start), angle_mode=mode, **kw)


def exact_from_coords(coords, mode="right"):
    """Angles and distances that close perfectly on the given (N, E) points."""
    n = len(coords)
    az = [azimuth(coords[(i + 1) % n][1] - coords[i][1], coords[(i + 1) % n][0] - coords[i][0]) for i in range(n)]
    rows = []
    for i in range(n):
        back = (az[i - 1] + 180) % 360
        ang = (az[i] - back) % 360 if mode == "right" else (back - az[i]) % 360
        d = math.dist(coords[i], coords[(i + 1) % n])
        rows.append((f"P{i + 1}", ang, d))
    return rows, az[0]


@pytest.fixture
def example():
    return make(EXAMPLE)
