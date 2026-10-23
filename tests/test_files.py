"""CSV import (including raw slope distance and zenith), field codes, linework and DXF."""

import math
from pathlib import Path

import ezdxf
import pytest

from traverse_doctor.codes import build_linework, parse_code, suggest_alias
from traverse_doctor.dxf import save_dxf
from traverse_doctor.engine import run
from traverse_doctor.fileio import coordinates_csv, load_csv, read_csv, write_csv

EXAMPLES = Path(__file__).resolve().parent.parent / "traverse_doctor" / "examples"


def test_example_file_reads_settings_and_side_shots():
    inp = load_csv(EXAMPLES / "site-loop.csv")
    assert len(inp.stations) == 5 and len(inp.sideshots) == 12
    assert inp.start_azimuth == pytest.approx(180 - (49 + 19 / 60 + 13 / 3600))
    assert inp.angle_mode == "right" and inp.required_precision == 10000


def test_raw_slope_distance_and_zenith():
    text = "Point,HA,SD,ZA\nA,90,100,90\nB,90,100,60-00-00\nC,90,100,90\nD,90,86.6025403784,90\n"
    inp = read_csv("# start_direction = N 90 E\n# angles = left\n" + text)
    assert inp.stations[1].distance == pytest.approx(100 * math.sin(math.radians(60)))


def test_csv_round_trip():
    inp = load_csv(EXAMPLES / "site-loop.csv")
    back = read_csv(write_csv(inp))
    assert [s.angle for s in back.stations] == pytest.approx([s.angle for s in inp.stations], abs=1e-6)
    assert [s.name for s in back.sideshots] == [s.name for s in inp.sideshots]
    assert back.start_azimuth == pytest.approx(inp.start_azimuth, abs=1e-6)


def test_bad_rows_name_the_row():
    with pytest.raises(ValueError, match="Row 3"):
        read_csv("Station,Angle,Distance\nA,90,100\nB,9x,100\nC,90,100\n")


def test_codes_and_linework():
    pc = parse_code("EP2 B")
    assert pc.code == "EP" and pc.string_id == "2" and pc.begin and pc.layer == "V-ROAD-EDGE"
    assert not parse_code("HYD").known and suggest_alias("HYD") == "FH"
    assert parse_code("HYD", {"HYD": "FH"}).layer == "V-WATR-HYDR"
    pts = [("1", parse_code("EP1 B")), ("2", parse_code("EP1")), ("3", parse_code("TREE")), ("4", parse_code("EP2")),
           ("5", parse_code("EP1 E")), ("6", parse_code("EP2")), ("7", parse_code("BLDG")), ("8", parse_code("BLDG")),
           ("9", parse_code("BLDG C"))]
    lines = {(ls.code, ls.string_id): ls for ls in build_linework(pts)}
    assert lines[("EP", "1")].points == ["1", "2", "5"]
    assert lines[("EP", "2")].points == ["4", "6"]
    assert lines[("BLDG", "")].closed and lines[("BLDG", "")].points == ["7", "8", "9"]


def test_side_shot_from_known_geometry():
    # station A at the origin, backsight B due north; 90 deg right and 50 ft puts the shot due east
    text = ("# start_n = 0\n# start_e = 0\n# start_direction = S 0 E\n# angles = left\n"
            "Type,Station,From,BS,Angle,Distance,Code\n"
            "TRAV,A,,,90,100,CP\nTRAV,B,,,90,100,CP\nTRAV,C,,,90,100,CP\nTRAV,D,,,90,100,CP\n"
            "SS,1,B,A,90,50,TREE\n")
    res = run(read_csv(text))
    shot = [p for p in res.points if p.name == "1"][0]
    # B is 100 ft south of A; looking north at A and turning 90 right faces east
    assert (shot.n, shot.e) == pytest.approx((-100.0, 50.0), abs=1e-9)


def test_dxf_has_layers_and_linework(tmp_path):
    res = run(load_csv(EXAMPLES / "site-loop.csv"), "lsq", aliases={"HYD": "FH"})
    path = tmp_path / "site.dxf"
    save_dxf(res, str(path))
    doc = ezdxf.readfile(path)
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"V-CTRL-TRAV", "V-CTRL-TRAV-RAW", "V-ROAD-EDGE", "V-BLDG", "V-WATR-HYDR", "V-SITE-FENC"} <= layers
    polys = list(doc.modelspace().query("LWPOLYLINE"))
    assert len(polys) == 2 + 3  # adjusted loop, raw loop, EP, BLDG, FENCE
    assert len(doc.modelspace().query("POINT")) == 17
    assert doc.header["$INSUNITS"] == 2
    csv_text = coordinates_csv(res)
    assert csv_text.splitlines()[0].startswith("Point,Northing,Easting")


@pytest.mark.parametrize("name,kind", [("site-loop", "none"), ("angle-blunder", "angle"),
                                       ("distance-blunder-raw", "distance")])
def test_examples_diagnose(name, kind):
    res = run(load_csv(EXAMPLES / f"{name}.csv"))
    assert res.finding.kind == kind
    assert (kind == "none") == res.passes
