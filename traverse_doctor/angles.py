"""Angle and direction parsing and formatting.

Angles are kept in decimal degrees internally.  Input accepts the forms a
field book or data collector export usually has: 101-24-30, 101 24 30,
101°24'30", 101d24m30s, or plain decimal degrees.  Directions can be an
azimuth (from north, clockwise) or a quadrant bearing like N 26 10 30 E.
"""

from __future__ import annotations

import math
import re

RHO = 206264.80624709636  # arcseconds per radian

_DMS = re.compile(
    r"^\s*(?P<sign>[-+])?\s*(?P<d>\d+(?:\.\d+)?)"
    r"(?:\s*(?:°|d|-|\s)\s*(?P<m>\d+(?:\.\d+)?)"
    r"(?:\s*(?:'|′|m|-|\s)\s*(?P<s>\d+(?:\.\d+)?)\s*(?:\"|″|''|s)?)?\s*(?:'|′|m)?)?\s*(?:°|d)?\s*$",
    re.IGNORECASE,
)
_BEARING = re.compile(r"^\s*(?P<ns>[NS])\s*(?P<angle>.*?)\s*(?P<ew>[EW])\s*$", re.IGNORECASE)


def parse_angle(text: str | float) -> float:
    """Parse an angle in DMS or decimal degrees and return decimal degrees."""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        raise ValueError("empty angle")
    m = _DMS.match(s)
    if not m:
        raise ValueError(f"can't read angle {text!r}; use 101-24-30, 101 24 30 or 101.4083")
    d = float(m.group("d"))
    mins = float(m.group("m") or 0)
    secs = float(m.group("s") or 0)
    if m.group("m") is not None and (mins >= 60 or secs >= 60):
        raise ValueError(f"minutes and seconds must be under 60 in {text!r}")
    value = d + mins / 60 + secs / 3600
    return -value if m.group("sign") == "-" else value


def parse_direction(text: str | float) -> float:
    """Parse an azimuth or a quadrant bearing and return an azimuth in degrees [0, 360)."""
    if isinstance(text, (int, float)):
        return float(text) % 360
    s = str(text).strip()
    b = _BEARING.match(s)
    if b:
        ang = parse_angle(b.group("angle")) if b.group("angle").strip() else 0.0
        if not 0 <= ang <= 90:
            raise ValueError(f"bearing angle must be 0 to 90 degrees in {text!r}")
        ns, ew = b.group("ns").upper(), b.group("ew").upper()
        az = {("N", "E"): ang, ("S", "E"): 180 - ang, ("S", "W"): 180 + ang, ("N", "W"): 360 - ang}[(ns, ew)]
        return az % 360
    return parse_angle(s) % 360


def wrap180(deg: float) -> float:
    """Wrap to (-180, 180]."""
    x = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if x == -180.0 else x


def dms_parts(deg: float, sec_decimals: int = 0) -> tuple[int, int, int, float]:
    sign = -1 if deg < 0 else 1
    total = round(abs(deg) * 3600, sec_decimals)
    d = int(total // 3600)
    m = int((total - d * 3600) // 60)
    s = round(total - d * 3600 - m * 60, sec_decimals)
    return sign, d, m, s


def fmt_dms(deg: float, sec_decimals: int = 0) -> str:
    sign, d, m, s = dms_parts(deg, sec_decimals)
    sec = f"{s:0{3 + sec_decimals if sec_decimals else 2}.{sec_decimals}f}"
    return f"{'-' if sign < 0 else ''}{d}°{m:02d}'{sec}\""


def fmt_seconds(sec: float, decimals: int = 1) -> str:
    """A small angle in arcseconds, shown as seconds (or minutes and seconds if large)."""
    if abs(sec) < 60:
        return f'{sec:+.{decimals}f}"'
    return ("+" if sec >= 0 else "-") + fmt_dms(abs(sec) / 3600, decimals)


def fmt_bearing(az: float, sec_decimals: int = 0) -> str:
    az = az % 360
    if az <= 90:
        ns, ew, ang = "N", "E", az
    elif az <= 180:
        ns, ew, ang = "S", "E", 180 - az
    elif az <= 270:
        ns, ew, ang = "S", "W", az - 180
    else:
        ns, ew, ang = "N", "W", 360 - az
    return f"{ns} {fmt_dms(ang, sec_decimals)} {ew}"


def azimuth(de: float, dn: float) -> float:
    """Azimuth in degrees of the vector (dE, dN), from north clockwise."""
    return math.degrees(math.atan2(de, dn)) % 360


def fmt_azimuth(az: float, sec_decimals: int = 0) -> str:
    text = fmt_dms(az % 360, sec_decimals)
    return text.replace("360°", "0°", 1) if text.startswith("360°") else text
