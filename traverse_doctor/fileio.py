"""Read and write the traverse CSV, and export coordinates.

The CSV is one row per traverse station (type TRAV, the default) or side shot
(type SS).  Settings can sit in comment lines at the top:

    # start_n = 5000
    # start_e = 5000
    # start_direction = S 49 19 13 E
    # angles = right            (right, left or azimuth)
    # units = ft
    # sigma_angle = 5           (arcseconds)
    # sigma_distance = 0.01     (constant part, ft or m)
    # sigma_ppm = 3
    # required_precision = 10000
    # project = Clemson P-lot control

Columns, matched by name and case-insensitively:

    Type, Station (or Point), From, BS, Angle (or HA, Azimuth, Bearing),
    Distance (or HD), SD, Zenith (or VA, ZA), Code, Description

A distance can be given as horizontal distance, or as slope distance plus
zenith angle straight from the instrument (HD = SD sin Z).  For side shots,
From is the occupied traverse station and BS the backsight (defaults to the
previous traverse station); Angle is turned to the right from the backsight.
"""

from __future__ import annotations

import csv
import io
import math

from .angles import fmt_azimuth, fmt_bearing, fmt_dms, parse_angle, parse_direction
from .model import Sideshot, Station, TraverseInput

ALIASES = {
    "type": ["type", "kind", "row"],
    "station": ["station", "point", "pt", "name", "sta", "id"],
    "from": ["from", "occupied", "occ", "setup", "at"],
    "bs": ["bs", "backsight", "back"],
    "angle": ["angle", "ha", "hz", "angle right", "angle_right", "horizontal angle", "azimuth", "az",
              "bearing", "direction"],
    "distance": ["distance", "hd", "dist", "horizontal distance", "horiz dist", "length"],
    "sd": ["sd", "slope distance", "slope"],
    "zenith": ["zenith", "va", "za", "vertical angle", "zenith angle"],
    "code": ["code", "field code", "desc code", "fc"],
    "description": ["description", "desc", "note", "notes", "remarks"],
}

SETTINGS = {
    "start_n": ("start_n", float), "start_e": ("start_e", float),
    "start_northing": ("start_n", float), "start_easting": ("start_e", float),
    "start_direction": ("start_azimuth", parse_direction), "start_azimuth": ("start_azimuth", parse_direction),
    "start_bearing": ("start_azimuth", parse_direction),
    "angles": ("angle_mode", str), "angle_mode": ("angle_mode", str), "units": ("units", str),
    "sigma_angle": ("sigma_angle_sec", float), "sigma_distance": ("sigma_dist_const", float),
    "sigma_ppm": ("sigma_dist_ppm", float), "required_precision": ("required_precision", float),
    "project": ("project", str), "party_chief": ("party_chief", str), "date": ("date", str),
}


def _column_map(header: list[str]) -> dict[str, int]:
    cols = {}
    lowered = [h.strip().lower() for h in header]
    for key, names in ALIASES.items():
        for name in names:
            if name in lowered:
                cols[key] = lowered.index(name)
                break
    return cols


def _distance(row: list[str], cols: dict[str, int], where: str) -> float:
    def cell(k):
        i = cols.get(k)
        return row[i].strip() if i is not None and i < len(row) else ""
    hd = cell("distance")
    if hd:
        return float(hd)
    sd, z = cell("sd"), cell("zenith")
    if sd and z:
        return float(sd) * math.sin(math.radians(parse_angle(z)))
    raise ValueError(f"{where}: needs a horizontal distance, or a slope distance and zenith angle.")


def read_csv(text: str) -> TraverseInput:
    settings = {}
    body = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            kv = s.lstrip("#").strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                v = v.split("  (")[0].strip()
                key = k.strip().lower().replace(" ", "_")
                if key in SETTINGS:
                    attr, conv = SETTINGS[key]
                    settings[attr] = conv(v)
            continue
        if s:
            body.append(line)
    rows = list(csv.reader(io.StringIO("\n".join(body))))
    if not rows:
        raise ValueError("The file has no data rows.")
    cols = _column_map(rows[0])
    for need in ("station", "angle"):
        if need not in cols:
            raise ValueError(f"No {need} column found. Header was: {', '.join(rows[0])}")
    header_angle = rows[0][cols["angle"]].strip().lower()
    if header_angle in ("azimuth", "az", "bearing", "direction") and "angle_mode" not in settings:
        settings["angle_mode"] = "azimuth"
    mode = settings.get("angle_mode", "right").lower()
    settings["angle_mode"] = mode

    def cell(row, k):
        i = cols.get(k)
        return row[i].strip() if i is not None and i < len(row) else ""

    stations, sideshots = [], []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        kind = (cell(row, "type") or "TRAV").upper()
        name = cell(row, "station")
        where = f"Row {n} ({name or 'no name'})"
        try:
            if kind in ("SS", "SIDESHOT", "SIDE", "TOPO"):
                sideshots.append(Sideshot(
                    name, cell(row, "from"), parse_angle(cell(row, "angle")), _distance(row, cols, where),
                    cell(row, "code"), cell(row, "description"), cell(row, "bs"),
                ))
            else:
                ang = cell(row, "angle")
                value = parse_direction(ang) if mode == "azimuth" else parse_angle(ang)
                stations.append(Station(name, value, _distance(row, cols, where), cell(row, "code"),
                                        cell(row, "description")))
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
    inp = TraverseInput(stations=stations, sideshots=sideshots, **settings)
    inp.validate()
    return inp


def load_csv(path: str) -> TraverseInput:
    with open(path, encoding="utf-8-sig") as f:
        return read_csv(f.read())


def write_csv(inp: TraverseInput) -> str:
    out = io.StringIO()
    out.write("# Traverse Doctor traverse file\n")
    out.write(f"# project = {inp.project}\n")
    out.write(f"# start_n = {inp.start_n:.3f}\n# start_e = {inp.start_e:.3f}\n")
    if inp.angle_mode != "azimuth":
        out.write(f"# start_direction = {_dms_text(inp.start_azimuth)}\n")
    out.write(f"# angles = {inp.angle_mode}\n# units = {inp.units}\n")
    out.write(f"# sigma_angle = {inp.sigma_angle_sec:g}\n# sigma_distance = {inp.sigma_dist_const:g}\n")
    out.write(f"# sigma_ppm = {inp.sigma_dist_ppm:g}\n# required_precision = {inp.required_precision:g}\n")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Type", "Station", "From", "BS", "Azimuth" if inp.angle_mode == "azimuth" else "Angle",
                "Distance", "Code", "Description"])
    for s in inp.stations:
        w.writerow(["TRAV", s.name, "", "", _dms_text(s.angle), f"{s.distance:.3f}", s.code, s.description])
    for ss in inp.sideshots:
        w.writerow(["SS", ss.name, ss.occupied, ss.backsight, _dms_text(ss.angle), f"{ss.distance:.3f}",
                    ss.code, ss.description])
    return out.getvalue()


def _dms_text(deg: float) -> str:
    text = fmt_dms(deg, 1)
    d, rest = text.split("°")
    m, s = rest.split("'")
    return f"{d}-{m}-{s.rstrip(chr(34))}"


def coordinates_csv(res) -> str:
    """P,N,E,Z,D style points file most CAD and data collector software can import."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Point", "Northing", "Easting", "Elevation", "Code", "Description"])
    for p in res.points:
        w.writerow([p.name, f"{p.n:.3f}", f"{p.e:.3f}", "", p.code.raw, p.description])
    return out.getvalue()


__all__ = ["read_csv", "load_csv", "write_csv", "coordinates_csv", "fmt_azimuth", "fmt_bearing"]


EXAMPLE_FILES = {
    "Site loop with side shots (closes)": "site-loop.csv",
    "Angle blunder at C": "angle-blunder.csv",
    "Raw slope distances with a distance blunder": "distance-blunder-raw.csv",
}


def example_path(filename: str) -> str:
    import os
    import sys

    base = getattr(sys, "_MEIPASS", None)
    root = os.path.join(base, "traverse_doctor") if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "examples", filename)
