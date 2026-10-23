"""Find the likely blunder when a traverse will not close.

Two classic hand methods, done by brute force so the reasoning is easy to
follow and to print in the report:

* Angle blunder.  If the angular misclosure is far over the allowable, put
  the whole misclosure on one angle at a time and recompute the linear
  misclosure.  Fixing the bad angle makes the traverse close; fixing any
  other angle leaves it badly open.

* Distance blunder.  If the angles close but the precision is poor, a single
  bad distance leaves a misclosure that points along that course.  For each
  course, find the distance change that best cancels the misclosure and see
  how much is left over.

A suspect is reported only when fixing it brings the traverse to the required
precision and clearly beats the next best candidate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .angles import fmt_dms, fmt_seconds
from .traverse import Closure, lat_dep, propagate_azimuths
from .model import TraverseInput


@dataclass
class Candidate:
    index: int
    label: str
    correction: float  # arcseconds for angles, length for distances
    remaining_misclosure: float
    precision_after: float


@dataclass
class Finding:
    kind: str  # angle, distance, direction, none
    headline: str
    detail: str
    suspect: Candidate | None = None
    candidates: list[Candidate] = field(default_factory=list)


def _precision(per: float, e: float) -> float:
    return math.inf if e < 1e-12 else per / e


def angle_candidates(cl: Closure, inp: TraverseInput) -> list[Candidate]:
    mis = cl.angular_misclosure_sec or 0.0
    out = []
    for k in range(cl.n):
        angles = list(cl.measured_angles)
        angles[k] -= mis / 3600.0
        az, _ = propagate_azimuths(angles, inp.start_azimuth, inp.angle_mode)
        lats, deps = lat_dep(az, cl.distances)
        e = math.hypot(sum(lats), sum(deps))
        out.append(Candidate(k, f"Angle at {cl.names[k]}", -mis, e, _precision(cl.perimeter, e)))
    return sorted(out, key=lambda c: c.remaining_misclosure)


def distance_candidates(cl: Closure) -> list[Candidate]:
    out = []
    for k in range(cl.n):
        a = math.radians(cl.azimuths[k])
        un, ue = math.cos(a), math.sin(a)
        delta = -(cl.sum_lat * un + cl.sum_dep * ue)
        e = math.hypot(cl.sum_lat + delta * un, cl.sum_dep + delta * ue)
        out.append(Candidate(k, f"Distance {cl.course_label(k)}", delta, e, _precision(cl.perimeter, e)))
    return sorted(out, key=lambda c: c.remaining_misclosure)


def _clear_winner(cands: list[Candidate], required: float) -> bool:
    if not cands:
        return False
    best = cands[0]
    second = cands[1].remaining_misclosure if len(cands) > 1 else math.inf
    return best.precision_after >= required and best.remaining_misclosure < 0.35 * second


def diagnose(cl: Closure, inp: TraverseInput) -> Finding:
    u = inp.unit_label
    req = inp.required_precision
    angle_bad = cl.angular_misclosure_sec is not None and abs(cl.angular_misclosure_sec) > cl.allowable_angular_sec
    precision_bad = cl.precision < req

    if angle_bad:
        cands = angle_candidates(cl, inp)
        if _clear_winner(cands, req):
            best = cands[0]
            fixed = cl.measured_angles[best.index] + best.correction / 3600.0
            return Finding(
                "angle",
                f"Likely angle blunder at station {cl.names[best.index]}.",
                f"The angular misclosure of {fmt_seconds(cl.angular_misclosure_sec)} is over the allowable "
                f"{cl.allowable_angular_sec:.0f}\". Moving it all onto the angle at {cl.names[best.index]} "
                f"(measured {fmt_dms(cl.measured_angles[best.index])}, would be {fmt_dms(fixed)}) leaves a linear "
                f"misclosure of {best.remaining_misclosure:.3f} {u} (1:{best.precision_after:,.0f}). The next best "
                f"station leaves {cands[1].remaining_misclosure:.3f} {u}. Check the field book for that angle, "
                f"for example a misread degree or a wrong backsight.",
                best, cands,
            )
        return Finding(
            "angle",
            "Angular misclosure is over the allowable, and no single angle explains it.",
            f"The angular misclosure is {fmt_seconds(cl.angular_misclosure_sec)} against an allowable of "
            f"{cl.allowable_angular_sec:.0f}\". Putting it on any one angle still leaves the traverse open, so "
            f"the error is spread over several angles or there is also a distance problem. Reobserve the angles.",
            None, cands,
        )

    if precision_bad:
        cands = distance_candidates(cl)
        if _clear_winner(cands, req):
            best = cands[0]
            k = best.index
            return Finding(
                "distance",
                f"Likely distance blunder on course {cl.course_label(k)}.",
                f"The angles close, but the precision is 1:{cl.precision:,.0f}, worse than the required "
                f"1:{req:,.0f}. The {cl.linear_misclosure:.3f} {u} misclosure runs nearly parallel to course "
                f"{cl.course_label(k)}. Changing that distance by {best.correction:+.3f} {u} (from "
                f"{cl.distances[k]:.3f} to {cl.distances[k] + best.correction:.3f}) would close the traverse to "
                f"1:{best.precision_after:,.0f}. Look for a transposed digit, a dropped tape length or a wrong "
                f"prism height on that course.",
                best, cands,
            )
        return Finding(
            "distance",
            f"Precision 1:{cl.precision:,.0f} is worse than the required 1:{req:,.0f}.",
            "No single distance explains the misclosure, so the error is likely spread over several courses "
            "or comes from small angle errors. Reobserve the longest or least certain courses first.",
            None, cands,
        )

    return Finding(
        "none",
        "No blunder found. The traverse meets the required precision.",
        f"Precision 1:{cl.precision:,.0f} meets the required 1:{req:,.0f}"
        + ("" if cl.angular_misclosure_sec is None else
           f", and the angular misclosure of {fmt_seconds(cl.angular_misclosure_sec)} is within the allowable "
           f"{cl.allowable_angular_sec:.0f}\"") + ".",
    )
