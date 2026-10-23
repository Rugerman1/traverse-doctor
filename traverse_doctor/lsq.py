"""Least squares adjustment of a closed loop traverse (parametric model).

Unknowns are the N and E coordinates of every station except the first,
which is held fixed.  Observations are the angles and distances (or the
course azimuths and distances in azimuth mode).  In angle mode the starting
direction is held fixed as a heavily weighted azimuth observation, which
gives the usual three redundancies of a closed loop (one angular, two linear).

Weights are 1 / sigma^2 with angles in arcseconds and distances in feet or
meters, so the a priori reference variance is 1.  After the adjustment the
module reports the reference variance with a chi-square test, the residuals,
standardized residuals for blunder screening (Baarda data snooping), and
standard error ellipses for each station.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .angles import RHO, azimuth, wrap180
from .model import TraverseInput
from .traverse import Adjustment, Closure, compass_rule

FIXED_AZ_SIGMA_SEC = 0.001
SNOOP_CRITICAL = 3.29  # two-tailed normal at alpha = 0.001

# chi-square quantiles (0.025, 0.975) for small degrees of freedom
_CHI2 = {
    1: (0.000982, 5.024), 2: (0.0506, 7.378), 3: (0.216, 9.348), 4: (0.484, 11.143), 5: (0.831, 12.833),
    6: (1.237, 14.449), 7: (1.690, 16.013), 8: (2.180, 17.535), 9: (2.700, 19.023), 10: (3.247, 20.483),
}


def chi2_bounds(df: int) -> tuple[float, float]:
    if df in _CHI2:
        return _CHI2[df]

    def wh(z):  # Wilson-Hilferty
        return df * (1 - 2 / (9 * df) + z * math.sqrt(2 / (9 * df))) ** 3
    return wh(-1.959964), wh(1.959964)


@dataclass
class Observation:
    kind: str  # angle, distance, azimuth, fixed_azimuth
    label: str
    at: int
    to: int  # foresight (angles) or far end (distances, azimuths)
    back: int  # backsight for angles, else -1
    value: float  # degrees or length
    sigma: float  # arcseconds or length
    residual: float = 0.0  # arcseconds or length
    std_residual: float = 0.0
    redundancy: float = 0.0  # local redundancy number r_i = qvv_ii / qll_ii

    @property
    def flagged(self) -> bool:
        return self.kind != "fixed_azimuth" and abs(self.std_residual) > SNOOP_CRITICAL


@dataclass
class Ellipse:
    station: str
    sigma_n: float
    sigma_e: float
    semi_major: float
    semi_minor: float
    major_azimuth: float  # degrees


@dataclass
class LeastSquares:
    adjustment: Adjustment
    observations: list[Observation]
    redundancy: int
    reference_variance: float
    chi2_low: float
    chi2_high: float
    iterations: int
    ellipses: list[Ellipse]

    @property
    def reference_std(self) -> float:
        return math.sqrt(self.reference_variance)

    @property
    def chi2_passes(self) -> bool:
        stat = self.redundancy * self.reference_variance
        return self.chi2_low <= stat <= self.chi2_high

    @property
    def flagged(self) -> list[Observation]:
        return sorted((o for o in self.observations if o.flagged), key=lambda o: -abs(o.std_residual))

    @property
    def worst(self) -> Observation | None:
        obs = [o for o in self.observations if o.kind != "fixed_azimuth" and o.redundancy > 1e-6]
        return max(obs, key=lambda o: abs(o.std_residual)) if obs else None


def _observations(cl: Closure, inp: TraverseInput) -> list[Observation]:
    n = cl.n
    obs = []
    if inp.angle_mode == "azimuth":
        for i in range(n):
            obs.append(Observation("azimuth", f"Azimuth {cl.course_label(i)}", i, (i + 1) % n, -1,
                                   cl.measured_angles[i], inp.sigma_angle_sec))
    else:
        obs.append(Observation("fixed_azimuth", f"Fixed direction {cl.course_label(0)}", 0, 1, -1,
                               inp.start_azimuth, FIXED_AZ_SIGMA_SEC))
        for i in range(n):
            obs.append(Observation("angle", f"Angle at {cl.names[i]}", i, (i + 1) % n, (i - 1) % n,
                                   cl.measured_angles[i], inp.sigma_angle_sec))
    for i in range(n):
        d = cl.distances[i]
        obs.append(Observation("distance", f"Distance {cl.course_label(i)}", i, (i + 1) % n, -1,
                               d, inp.sigma_distance(d)))
    return obs


def adjust(cl: Closure, inp: TraverseInput, max_iter: int = 25, tol: float = 1e-7) -> LeastSquares:
    n = cl.n
    start = compass_rule(cl, inp)
    xy = np.array([start.coords[name] for name in cl.names], dtype=float)  # rows: (N, E)
    obs = _observations(cl, inp)
    m, u = len(obs), 2 * (n - 1)
    sigma = np.array([o.sigma for o in obs])
    p = 1.0 / sigma ** 2
    sign = 1.0 if inp.angle_mode == "right" else -1.0

    def col(k):  # columns for station k, or None for the fixed station
        return None if k == 0 else (2 * (k - 1), 2 * (k - 1) + 1)

    def az_terms(i, j):
        dn, de = xy[j] - xy[i]
        d2 = dn * dn + de * de
        a = azimuth(de, dn)
        # d(Az)/d(N_j), d(Az)/d(E_j) in arcseconds per unit length
        return a, (-de / d2 * RHO, dn / d2 * RHO)

    def build():
        a_mat = np.zeros((m, u))
        f = np.zeros(m)  # observed minus computed
        for r, o in enumerate(obs):
            i, j = o.at, o.to
            if o.kind == "distance":
                dn, de = xy[j] - xy[i]
                d = math.hypot(dn, de)
                f[r] = o.value - d
                g = (dn / d, de / d)
                for k, s in ((j, 1.0), (i, -1.0)):
                    c = col(k)
                    if c:
                        a_mat[r, c[0]] += s * g[0]
                        a_mat[r, c[1]] += s * g[1]
                continue
            if o.kind in ("azimuth", "fixed_azimuth"):
                a, g = az_terms(i, j)
                f[r] = wrap180(o.value - a) * 3600.0
                terms = [(j, 1.0, g), (i, -1.0, g)]
            else:  # angle = sign * (Az(i->f) - Az(i->b))
                af, gf = az_terms(i, j)
                ab, gb = az_terms(i, o.back)
                f[r] = wrap180(o.value - sign * (af - ab)) * 3600.0
                terms = [(j, sign, gf), (i, -sign, gf), (o.back, -sign, gb), (i, sign, gb)]
            for k, s, g in terms:
                c = col(k)
                if c:
                    a_mat[r, c[0]] += s * g[0]
                    a_mat[r, c[1]] += s * g[1]
        return a_mat, f

    iterations = 0
    for iterations in range(1, max_iter + 1):
        a_mat, f = build()
        nmat = a_mat.T @ (a_mat * p[:, None])
        dx = np.linalg.solve(nmat, a_mat.T @ (p * f))
        xy[1:] += dx.reshape(-1, 2)
        if np.max(np.abs(dx)) < tol:
            break
    a_mat, f = build()
    v = -f  # residual = adjusted (computed) minus observed
    qxx = np.linalg.inv(a_mat.T @ (a_mat * p[:, None]))
    r_df = m - u
    vtpv = float(v @ (p * v))
    s02 = vtpv / r_df if r_df > 0 else 0.0
    qll = sigma ** 2
    qvv = qll - np.einsum("ij,jk,ik->i", a_mat, qxx, a_mat)
    for k, o in enumerate(obs):
        o.residual = float(v[k])
        o.redundancy = float(max(qvv[k], 0.0) / qll[k])
        o.std_residual = float(v[k] / math.sqrt(qvv[k])) if qvv[k] > 1e-12 * qll[k] else 0.0

    coords = {name: (float(xy[k, 0]), float(xy[k, 1])) for k, name in enumerate(cl.names)}
    adj_az, adj_d = [], []
    for i in range(n):
        dn, de = xy[(i + 1) % n] - xy[i]
        adj_az.append(azimuth(de, dn))
        adj_d.append(math.hypot(dn, de))
    adjustment = Adjustment("Least squares", coords, adj_azimuths=adj_az, adj_distances=adj_d)

    ellipses = [Ellipse(cl.names[0], 0.0, 0.0, 0.0, 0.0, 0.0)]
    for k in range(1, n):
        c = col(k)
        q = qxx[np.ix_(c, c)] * s02
        qnn, qee, qne = q[0, 0], q[1, 1], q[0, 1]
        half = math.sqrt(((qnn - qee) / 2) ** 2 + qne ** 2)
        mid = (qnn + qee) / 2
        major = math.sqrt(max(mid + half, 0.0))
        minor = math.sqrt(max(mid - half, 0.0))
        t = math.degrees(0.5 * math.atan2(2 * qne, qnn - qee)) % 180
        ellipses.append(Ellipse(cl.names[k], math.sqrt(max(qnn, 0)), math.sqrt(max(qee, 0)), major, minor, t))

    lo, hi = chi2_bounds(r_df) if r_df > 0 else (0.0, math.inf)
    return LeastSquares(adjustment, obs, r_df, s02, lo, hi, iterations, ellipses)
