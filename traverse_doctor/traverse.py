"""Closed loop traverse: angular closure, latitudes and departures, linear
misclosure and precision, compass and transit rule adjustments, and area.

Conventions: azimuths from north clockwise in degrees, latitude = d cos(Az)
(north positive), departure = d sin(Az) (east positive).  Course i runs from
station i to station i+1, and the last course closes on station 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .angles import azimuth, fmt_dms, wrap180
from .model import TraverseInput


def propagate_azimuths(angles: list[float], start_az: float, mode: str) -> tuple[list[float], float]:
    """Carry azimuths around the loop from the first course.

    Returns the azimuth of every course and the azimuth misclosure in degrees:
    the first course's azimuth as recomputed through the angle at station 1,
    minus the given one.
    """
    sign = 1.0 if mode == "right" else -1.0
    n = len(angles)
    az = [start_az % 360]
    for i in range(1, n):
        az.append((az[i - 1] + 180.0 + sign * angles[i]) % 360)
    closing = (az[n - 1] + 180.0 + sign * angles[0]) % 360
    return az, wrap180(closing - start_az)


def lat_dep(az: list[float], dist: list[float]) -> tuple[list[float], list[float]]:
    lats = [d * math.cos(math.radians(a)) for a, d in zip(az, dist)]
    deps = [d * math.sin(math.radians(a)) for a, d in zip(az, dist)]
    return lats, deps


def shoelace_area(coords: list[tuple[float, float]]) -> float:
    """Area enclosed by (N, E) points, by coordinates (always positive)."""
    s = 0.0
    n = len(coords)
    for i in range(n):
        n1, e1 = coords[i]
        n2, e2 = coords[(i + 1) % n]
        s += e1 * n2 - e2 * n1
    return abs(s) / 2.0


@dataclass
class Closure:
    names: list[str]
    distances: list[float]
    angle_mode: str
    measured_angles: list[float]  # as entered (angles, or azimuths in azimuth mode)
    angular_misclosure_sec: float | None  # sum of measured minus theoretical, arcseconds
    allowable_angular_sec: float | None
    angle_correction_sec: float  # applied to every angle
    balanced_angles: list[float]
    azimuths: list[float]  # balanced
    lats: list[float]
    deps: list[float]
    sum_lat: float
    sum_dep: float
    perimeter: float
    sum_theoretical_note: str = ""

    @property
    def n(self) -> int:
        return len(self.names)

    @property
    def linear_misclosure(self) -> float:
        return math.hypot(self.sum_lat, self.sum_dep)

    @property
    def misclosure_azimuth(self) -> float:
        """Direction of the closing error: from where the traverse should end to where it ends."""
        return azimuth(self.sum_dep, self.sum_lat)

    @property
    def precision(self) -> float:
        """Relative precision as N in 1:N (infinite for a perfect closure)."""
        e = self.linear_misclosure
        return math.inf if e < 1e-9 else self.perimeter / e

    def course_label(self, i: int) -> str:
        return f"{self.names[i]}-{self.names[(i + 1) % self.n]}"


@dataclass
class Adjustment:
    method: str
    coords: dict[str, tuple[float, float]]  # name -> (N, E)
    corr_lat: list[float] = field(default_factory=list)
    corr_dep: list[float] = field(default_factory=list)
    adj_azimuths: list[float] = field(default_factory=list)
    adj_distances: list[float] = field(default_factory=list)

    @property
    def area(self) -> float:
        return shoelace_area(list(self.coords.values()))


def compute_closure(inp: TraverseInput) -> Closure:
    inp.validate()
    names = [s.name for s in inp.stations]
    dist = [s.distance for s in inp.stations]
    measured = [s.angle for s in inp.stations]
    n = len(names)
    if inp.angle_mode == "azimuth":
        az = [a % 360 for a in measured]
        mis_sec = allow = None
        corr = 0.0
        balanced = list(az)
        note = "Courses entered as azimuths or bearings, so there is no angular closure."
    else:
        _, az_mis = propagate_azimuths(measured, inp.start_azimuth, inp.angle_mode)
        mis = az_mis if inp.angle_mode == "right" else -az_mis  # as sum(measured) - sum(theoretical)
        mis_sec = mis * 3600.0
        allow = 3.0 * inp.sigma_angle_sec * math.sqrt(n)
        corr = -mis_sec / n
        balanced = [a + corr / 3600.0 for a in measured]
        az, _ = propagate_azimuths(balanced, inp.start_azimuth, inp.angle_mode)
        interior = (n - 2) * 180
        total = sum(measured)
        kind = "interior" if abs(total - interior) <= abs(total - (n + 2) * 180) else "exterior"
        note = (f"Angles sum to {fmt_dms(total)}. {kind.capitalize()} angles of a {n}-sided loop should sum to "
                f"{interior if kind == 'interior' else (n + 2) * 180}°00'00\".")
    lats, deps = lat_dep(az, dist)
    return Closure(
        names=names, distances=dist, angle_mode=inp.angle_mode, measured_angles=measured,
        angular_misclosure_sec=mis_sec, allowable_angular_sec=allow, angle_correction_sec=corr,
        balanced_angles=balanced, azimuths=az, lats=lats, deps=deps,
        sum_lat=sum(lats), sum_dep=sum(deps), perimeter=sum(dist), sum_theoretical_note=note,
    )


def _apply(cl: Closure, inp: TraverseInput, method: str, corr_lat: list[float], corr_dep: list[float]) -> Adjustment:
    coords = {}
    n_, e_ = inp.start_n, inp.start_e
    adj_az, adj_d = [], []
    for i, name in enumerate(cl.names):
        coords[name] = (n_, e_)
        lat = cl.lats[i] + corr_lat[i]
        dep = cl.deps[i] + corr_dep[i]
        adj_az.append(azimuth(dep, lat))
        adj_d.append(math.hypot(lat, dep))
        n_ += lat
        e_ += dep
    return Adjustment(method, coords, corr_lat, corr_dep, adj_az, adj_d)


def compass_rule(cl: Closure, inp: TraverseInput) -> Adjustment:
    """Bowditch: corrections proportional to course length."""
    p = cl.perimeter
    corr_lat = [-cl.sum_lat * d / p for d in cl.distances]
    corr_dep = [-cl.sum_dep * d / p for d in cl.distances]
    return _apply(cl, inp, "Compass rule", corr_lat, corr_dep)


def transit_rule(cl: Closure, inp: TraverseInput) -> Adjustment:
    """Corrections proportional to the size of each latitude and departure."""
    sl = sum(abs(x) for x in cl.lats) or 1.0
    sd = sum(abs(x) for x in cl.deps) or 1.0
    corr_lat = [-cl.sum_lat * abs(x) / sl for x in cl.lats]
    corr_dep = [-cl.sum_dep * abs(x) / sd for x in cl.deps]
    return _apply(cl, inp, "Transit rule", corr_lat, corr_dep)


def runs_clockwise(coords: list[tuple[float, float]]) -> bool:
    """True if the (N, E) loop runs clockwise on a north-up map."""
    s = 0.0
    n = len(coords)
    for i in range(n):
        n1, e1 = coords[i]
        n2, e2 = coords[(i + 1) % n]
        s += e1 * n2 - e2 * n1
    return s < 0
