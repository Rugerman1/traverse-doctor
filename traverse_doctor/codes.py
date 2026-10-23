"""Field codes: map point codes to CAD layers and build linework.

A code is the first word of the code field, for example `EP`, `TBC2` or
`FENCE`.  Trailing digits name separate strings of the same feature, so
`EP1` and `EP2` are two edges of pavement.  Control words after the code:

    B   begin a new line string
    E   end the current line string after this point
    C   close the string back to its first point (buildings)

Codes that are not in the library go to a layer named after the code, and the
app suggests the closest library code (offline by string similarity, or by
Claude if an API key is set).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# code: (layer, description, draws a line, AutoCAD color index)
LIBRARY: dict[str, tuple[str, str, bool, int]] = {
    "CP": ("V-CTRL", "Control point", False, 1),
    "TRAV": ("V-CTRL", "Traverse station", False, 1),
    "BM": ("V-CTRL-BM", "Benchmark", False, 1),
    "IPF": ("V-PROP-MON", "Iron pin found", False, 6),
    "IPS": ("V-PROP-MON", "Iron pin set", False, 6),
    "CMF": ("V-PROP-MON", "Concrete monument found", False, 6),
    "PL": ("V-PROP-LINE", "Property line", True, 6),
    "EP": ("V-ROAD-EDGE", "Edge of pavement", True, 8),
    "CL": ("V-ROAD-CNTR", "Road centerline", True, 3),
    "TBC": ("V-ROAD-CURB", "Top back of curb", True, 8),
    "GUT": ("V-ROAD-CURB", "Gutter / flow line", True, 8),
    "SW": ("V-SITE-WALK", "Sidewalk edge", True, 9),
    "DW": ("V-SITE-DRIVE", "Driveway edge", True, 9),
    "BLDG": ("V-BLDG", "Building corner", True, 7),
    "FENCE": ("V-SITE-FENC", "Fence", True, 30),
    "WALL": ("V-SITE-WALL", "Retaining wall", True, 30),
    "DITCH": ("V-STRM-DTCH", "Ditch flow line", True, 5),
    "TOB": ("V-TOPO-BANK", "Top of bank", True, 5),
    "TOE": ("V-TOPO-BANK", "Toe of slope", True, 5),
    "WE": ("V-STRM-WATR", "Water's edge", True, 5),
    "GS": ("V-TOPO-GRND", "Ground shot", False, 254),
    "TREE": ("V-SITE-VEG", "Tree", False, 3),
    "BUSH": ("V-SITE-VEG", "Shrub", False, 3),
    "MH": ("V-SSWR-MH", "Manhole", False, 4),
    "SSMH": ("V-SSWR-MH", "Sanitary manhole", False, 4),
    "SDMH": ("V-STRM-MH", "Storm manhole", False, 5),
    "CB": ("V-STRM-INLT", "Catch basin / inlet", False, 5),
    "CULV": ("V-STRM-CULV", "Culvert end", False, 5),
    "FH": ("V-WATR-HYDR", "Fire hydrant", False, 4),
    "WV": ("V-WATR-VALV", "Water valve", False, 4),
    "WM": ("V-WATR-METR", "Water meter", False, 4),
    "PP": ("V-POWR-POLE", "Power pole", False, 2),
    "LP": ("V-POWR-LITE", "Light pole", False, 2),
    "GUY": ("V-POWR-GUY", "Guy anchor", False, 2),
    "TELE": ("V-COMM-PED", "Telephone pedestal", False, 2),
    "SIGN": ("V-ROAD-SIGN", "Sign", False, 2),
    "MB": ("V-SITE-MBOX", "Mailbox", False, 2),
}

_CODE = re.compile(r"^([A-Za-z]+)(\d*)$")


@dataclass
class ParsedCode:
    raw: str
    code: str  # library key or the unknown code itself, upper case
    string_id: str
    begin: bool = False
    end: bool = False
    close: bool = False
    known: bool = True

    @property
    def layer(self) -> str:
        return LIBRARY[self.code][0] if self.known else f"V-UNK-{self.code or 'NOCODE'}"

    @property
    def is_line(self) -> bool:
        return LIBRARY[self.code][2] if self.known else False

    @property
    def color(self) -> int:
        return LIBRARY[self.code][3] if self.known else 7

    @property
    def description(self) -> str:
        return LIBRARY[self.code][1] if self.known else "Unknown code"


def parse_code(raw: str, aliases: dict[str, str] | None = None) -> ParsedCode:
    words = (raw or "").upper().replace(",", " ").split()
    if not words:
        return ParsedCode(raw or "", "", "", known=False)
    m = _CODE.match(words[0])
    base, sid = (m.group(1), m.group(2)) if m else (words[0], "")
    if aliases and base in aliases:
        base = aliases[base]
    flags = set(words[1:])
    return ParsedCode(raw, base, sid, "B" in flags, "E" in flags, "C" in flags, base in LIBRARY)


def suggest_alias(code: str) -> str | None:
    """Closest library code by spelling, for codes the library does not know."""
    if not code:
        return None
    hit = difflib.get_close_matches(code.upper(), list(LIBRARY), n=1, cutoff=0.5)
    if hit:
        return hit[0]
    # common spelled-out words
    for key, (_, desc, _, _) in LIBRARY.items():
        if code.lower() in desc.lower().replace("'", ""):
            return key
    return None


@dataclass
class LineString:
    code: str
    string_id: str
    layer: str
    color: int
    points: list[str] = field(default_factory=list)
    closed: bool = False


def build_linework(points: list[tuple[str, ParsedCode]]) -> list[LineString]:
    """Connect coded points in the order they were shot."""
    open_strings: dict[tuple[str, str], LineString] = {}
    done: list[LineString] = []
    for name, pc in points:
        if not pc.is_line:
            continue
        key = (pc.code, pc.string_id)
        if pc.begin and key in open_strings:
            done.append(open_strings.pop(key))
        ls = open_strings.get(key)
        if ls is None:
            ls = LineString(pc.code, pc.string_id, pc.layer, pc.color)
            open_strings[key] = ls
        ls.points.append(name)
        if pc.close or pc.end:
            ls.closed = pc.close
            done.append(open_strings.pop(key))
    done.extend(open_strings.values())
    return [ls for ls in done if len(ls.points) >= 2]
