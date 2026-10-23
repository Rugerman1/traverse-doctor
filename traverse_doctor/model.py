"""Inputs for a closed loop traverse and its side shots."""

from __future__ import annotations

from dataclasses import dataclass, field

ANGLE_MODES = ("right", "left", "azimuth")


@dataclass
class Station:
    """One traverse station and the course that leaves it.

    `angle` is the horizontal angle at this station from the previous station
    (backsight) to the next one (foresight), in degrees, turned to the right or
    the left depending on `TraverseInput.angle_mode`.  In azimuth mode it is the
    azimuth of the course leaving this station instead.  `distance` is the
    horizontal distance to the next station; the last station's course closes
    back on the first.
    """

    name: str
    angle: float
    distance: float
    code: str = ""
    description: str = ""


@dataclass
class Sideshot:
    """A point located from a traverse station by angle right and distance.

    The angle is turned to the right from `backsight` (by default the previous
    traverse station) to the point.
    """

    name: str
    occupied: str
    angle: float
    distance: float
    code: str = ""
    description: str = ""
    backsight: str = ""


@dataclass
class TraverseInput:
    stations: list[Station]
    start_n: float = 5000.0
    start_e: float = 5000.0
    start_azimuth: float = 0.0  # azimuth of the first course (station 1 to station 2); unused in azimuth mode
    angle_mode: str = "right"
    units: str = "ft"
    sigma_angle_sec: float = 5.0
    sigma_dist_const: float = 0.01  # ft or m
    sigma_dist_ppm: float = 3.0
    required_precision: float = 10000.0  # 1 : N
    sideshots: list[Sideshot] = field(default_factory=list)
    project: str = ""
    party_chief: str = ""
    date: str = ""
    notes: str = ""

    def validate(self) -> None:
        if len(self.stations) < 3:
            raise ValueError("A closed traverse needs at least 3 stations.")
        if self.angle_mode not in ANGLE_MODES:
            raise ValueError(f"angle_mode must be one of {ANGLE_MODES}")
        names = [s.name for s in self.stations]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError("Station names must be unique: " + ", ".join(dupes))
        for s in self.stations:
            if not s.name:
                raise ValueError("Every station needs a name.")
            if s.distance <= 0:
                raise ValueError(f"Distance from {s.name} must be positive.")
        if self.sigma_angle_sec <= 0 or self.sigma_dist_const < 0 or self.sigma_dist_ppm < 0:
            raise ValueError("Standard deviations must be positive.")
        if self.sigma_dist_const == 0 and self.sigma_dist_ppm == 0:
            raise ValueError("Distance standard deviation can't be zero.")
        known = set(names)
        for ss in self.sideshots:
            if ss.occupied not in known:
                raise ValueError(f"Side shot {ss.name} is taken from {ss.occupied!r}, which is not a traverse station.")
            if ss.backsight and ss.backsight not in known:
                raise ValueError(f"Side shot {ss.name} backsights {ss.backsight!r}, which is not a traverse station.")

    @property
    def unit_label(self) -> str:
        return "ft" if self.units == "ft" else "m"

    def sigma_distance(self, d: float) -> float:
        return (self.sigma_dist_const ** 2 + (self.sigma_dist_ppm * 1e-6 * d) ** 2) ** 0.5
