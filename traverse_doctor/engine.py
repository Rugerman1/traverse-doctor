"""Runs the whole job: closure, the three adjustments, blunder diagnosis,
side shot coordinates and coded linework."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .angles import fmt_azimuth, fmt_bearing, fmt_seconds
from .blunders import Finding, diagnose
from .codes import LineString, ParsedCode, build_linework, parse_code, suggest_alias
from .lsq import LeastSquares, adjust
from .model import TraverseInput
from .traverse import Adjustment, Closure, compass_rule, compute_closure, runs_clockwise, transit_rule

METHODS = ("compass", "transit", "lsq")
METHOD_LABELS = {"compass": "Compass rule", "transit": "Transit rule", "lsq": "Least squares"}


@dataclass
class Point:
    name: str
    n: float
    e: float
    code: ParsedCode
    description: str
    is_station: bool


@dataclass
class Result:
    inp: TraverseInput
    closure: Closure
    compass: Adjustment
    transit: Adjustment
    lsq: LeastSquares
    finding: Finding
    method: str
    points: list[Point] = field(default_factory=list)
    linework: list[LineString] = field(default_factory=list)
    unknown_codes: dict[str, str | None] = field(default_factory=dict)  # code -> suggested library code
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def chosen(self) -> Adjustment:
        return {"compass": self.compass, "transit": self.transit, "lsq": self.lsq.adjustment}[self.method]

    @property
    def passes(self) -> bool:
        cl = self.closure
        ang_ok = cl.angular_misclosure_sec is None or abs(cl.angular_misclosure_sec) <= cl.allowable_angular_sec
        return ang_ok and cl.precision >= self.inp.required_precision

    @property
    def area(self) -> float:
        return self.chosen.area

    def area_text(self) -> str:
        a = self.area
        if self.inp.units == "ft":
            return f"{a:,.1f} sq ft ({a / 43560:.4f} ac)"
        return f"{a:,.2f} m² ({a / 10000:.4f} ha)"


def side_shot_coords(inp: TraverseInput, coords: dict[str, tuple[float, float]]) -> list[tuple]:
    names = [s.name for s in inp.stations]
    out = []
    for ss in inp.sideshots:
        k = names.index(ss.occupied)
        bs = ss.backsight or names[(k - 1) % len(names)]
        n0, e0 = coords[ss.occupied]
        nb, eb = coords[bs]
        az_bs = math.degrees(math.atan2(eb - e0, nb - n0))
        az = math.radians(az_bs + ss.angle)
        out.append((ss, n0 + ss.distance * math.cos(az), e0 + ss.distance * math.sin(az)))
    return out


def run(inp: TraverseInput, method: str = "compass", aliases: dict[str, str] | None = None) -> Result:
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    cl = compute_closure(inp)
    comp = compass_rule(cl, inp)
    trans = transit_rule(cl, inp)
    ls = adjust(cl, inp)
    finding = diagnose(cl, inp)
    res = Result(inp, cl, comp, trans, ls, finding, method)
    coords = res.chosen.coords
    for st in inp.stations:
        n, e = coords[st.name]
        res.points.append(Point(st.name, n, e, parse_code(st.code or "TRAV", aliases), st.description, True))
    for ss, n, e in side_shot_coords(inp, coords):
        res.points.append(Point(ss.name, n, e, parse_code(ss.code, aliases), ss.description, False))
    res.linework = build_linework([(p.name, p.code) for p in res.points if not p.is_station])
    for p in res.points:
        if not p.code.known and p.code.code and p.code.code not in res.unknown_codes:
            res.unknown_codes[p.code.code] = suggest_alias(p.code.code)
    seen = set()
    for p in res.points:
        if p.name in seen:
            res.warnings.append(f"Point name {p.name} is used more than once.")
        seen.add(p.name)
    if inp.angle_mode != "azimuth":
        cw = runs_clockwise([coords[s.name] for s in inp.stations])
        res.notes.append(
            f"The loop runs {'clockwise' if cw else 'counterclockwise'} on the plot. If it looks mirrored compared "
            f"with your sketch, the angles were turned the other way: switch between angles right and angles left."
        )
    if not ls.chi2_passes and ls.redundancy > 0:
        res.warnings.append(
            f"Least squares reference variance {ls.reference_variance:.2f} fails the chi-square test "
            f"(bounds {ls.chi2_low / ls.redundancy:.2f} to {ls.chi2_high / ls.redundancy:.2f}). The standard "
            f"deviations are too optimistic or there is a blunder."
        )
    return res


def summary_dict(res: Result) -> dict:
    """Computed numbers handed to the narrative writer.  Nothing here is
    recomputed downstream; the narrative may only quote these."""
    cl, inp, ls = res.closure, res.inp, res.lsq
    worst = ls.worst
    return {
        "project": inp.project,
        "units": inp.unit_label,
        "stations": cl.n,
        "perimeter": round(cl.perimeter, 3),
        "angle_mode": {"right": "angles right", "left": "angles left", "azimuth": "azimuths per course"}[inp.angle_mode],
        "angular_misclosure": None if cl.angular_misclosure_sec is None else fmt_seconds(cl.angular_misclosure_sec),
        "allowable_angular_misclosure": None if cl.allowable_angular_sec is None else f'{cl.allowable_angular_sec:.0f}"',
        "angle_correction_each": None if cl.angular_misclosure_sec is None else fmt_seconds(cl.angle_correction_sec),
        "sum_latitudes": round(cl.sum_lat, 3),
        "sum_departures": round(cl.sum_dep, 3),
        "linear_misclosure": round(cl.linear_misclosure, 3),
        "misclosure_direction": fmt_bearing(cl.misclosure_azimuth),
        "precision": "perfect" if math.isinf(cl.precision) else f"1:{cl.precision:,.0f}",
        "required_precision": f"1:{inp.required_precision:,.0f}",
        "meets_requirements": res.passes,
        "coordinates_from": METHOD_LABELS[res.method],
        "area": res.area_text(),
        "least_squares": {
            "redundancy": ls.redundancy,
            "reference_variance": round(ls.reference_variance, 3),
            "chi_square_passes": ls.chi2_passes,
            "largest_standardized_residual": None if worst is None else {
                "observation": worst.label, "value": round(worst.std_residual, 2),
                "flagged": worst.flagged,
            },
            "flagged_observations": [o.label for o in ls.flagged],
        },
        "blunder_finding": {"kind": res.finding.kind, "headline": res.finding.headline, "detail": res.finding.detail},
        "side_shots": len(inp.sideshots),
        "unknown_codes": {k: v for k, v in res.unknown_codes.items()},
        "warnings": res.warnings,
        "notes": res.notes,
        "start_direction": None if inp.angle_mode == "azimuth" else fmt_azimuth(inp.start_azimuth),
    }
