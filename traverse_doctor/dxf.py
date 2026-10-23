"""DXF output: adjusted traverse, stations, side shots and coded linework,
one layer per feature, in ground coordinates (X = easting, Y = northing)."""

from __future__ import annotations

import ezdxf

from .engine import Result

TRAV_LAYER = "V-CTRL-TRAV"
RAW_LAYER = "V-CTRL-TRAV-RAW"
LABEL_LAYER = "V-ANNO-PNTS"


def build_dxf(res: Result, include_raw: bool = True):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 2 if res.inp.units == "ft" else 6
    msp = doc.modelspace()
    size = max(res.closure.perimeter / 400.0, 0.5)  # text height scaled to the job

    def layer(name, color, desc=""):
        if name not in doc.layers:
            doc.layers.add(name, color=color).description = desc

    layer(TRAV_LAYER, 1, f"Traverse adjusted by {res.chosen.method}")
    layer(LABEL_LAYER, 7, "Point labels")
    coords = res.chosen.coords
    loop = [(coords[s.name][1], coords[s.name][0]) for s in res.inp.stations]
    msp.add_lwpolyline(loop, close=True, dxfattribs={"layer": TRAV_LAYER})

    if include_raw:
        layer(RAW_LAYER, 8, "Unadjusted traverse (shows the misclosure)")
        e, n = res.inp.start_e, res.inp.start_n
        raw = [(e, n)]
        for lat, dep in zip(res.closure.lats, res.closure.deps):
            n += lat
            e += dep
            raw.append((e, n))
        msp.add_lwpolyline(raw, dxfattribs={"layer": RAW_LAYER, "linetype": "DASHED"})

    by_name = {}
    for p in res.points:
        lay = TRAV_LAYER if p.is_station else p.code.layer
        layer(lay, p.code.color, p.code.description)
        msp.add_point((p.e, p.n), dxfattribs={"layer": lay})
        label = p.name if not p.code.raw else f"{p.name} {p.code.raw}"
        msp.add_text(label, height=size, dxfattribs={"layer": LABEL_LAYER}).set_placement(
            (p.e + size * 0.6, p.n + size * 0.6))
        by_name[p.name] = (p.e, p.n)

    for ls in res.linework:
        layer(ls.layer, ls.color)
        msp.add_lwpolyline([by_name[name] for name in ls.points], close=ls.closed, dxfattribs={"layer": ls.layer})
    return doc


def save_dxf(res: Result, path: str, include_raw: bool = True) -> None:
    build_dxf(res, include_raw).saveas(path)
