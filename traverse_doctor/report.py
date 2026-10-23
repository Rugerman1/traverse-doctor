"""PDF closure report built with ReportLab."""

from __future__ import annotations

import datetime as dt
import io
import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import __version__
from .angles import fmt_azimuth, fmt_bearing, fmt_dms, fmt_seconds
from .engine import Result
from .plots import plan_png

DISCLAIMER = (
    "Traverse Doctor is a student-built tool for checking traverse computations. "
    "It is not a substitute for a licensed surveyor's review and is not for boundary or construction work."
)


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.grey))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=9.5, leading=13))
    ss.add(ParagraphStyle("H", parent=ss["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4))
    return ss


def _table(rows, col_widths=None, header=True, align_right_from=1):
    t = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
        ]
    t.setStyle(TableStyle(style))
    return t


def build_pdf(res: Result, narrative: str, narrative_source: str, path: str) -> None:
    ss = _styles()
    cl, inp, ls = res.closure, res.inp, res.lsq
    u = inp.unit_label
    story = [Paragraph(f"Traverse Closure Report{': ' + inp.project if inp.project else ''}", ss["Title"])]
    meta = [
        ["Project", inp.project or "-", "Date", inp.date or dt.date.today().isoformat()],
        ["Party chief", inp.party_chief or "-", "Software", f"Traverse Doctor v{__version__}"],
        ["Start point", f"{cl.names[0]}: N {inp.start_n:,.3f}, E {inp.start_e:,.3f}", "Start direction",
         "-" if inp.angle_mode == "azimuth" else f"{fmt_bearing(inp.start_azimuth)} ({cl.course_label(0)})"],
    ]
    story.append(_table(meta, col_widths=[1.0 * inch, 2.6 * inch, 1.1 * inch, 2.3 * inch], header=False))
    story.append(Spacer(1, 8))

    color = "#1a7f37" if res.passes else "#b42318"
    prec = "perfect closure" if math.isinf(cl.precision) else f"1:{cl.precision:,.0f}"
    story.append(Paragraph(
        f"<font color='{color}'><b>{'MEETS' if res.passes else 'DOES NOT MEET'} REQUIREMENTS</b></font>. "
        f"Precision {prec} (required 1:{inp.required_precision:,.0f}). {res.finding.headline}", ss["Body"]))
    if res.finding.kind != "none":
        story.append(Paragraph(res.finding.detail, ss["Body"]))
    for w in res.warnings:
        story.append(Paragraph(f"<font color='#b42318'><b>Warning:</b> {w}</font>", ss["Body"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Summary", ss["H"]))
    story.append(Paragraph(narrative.replace("\n\n", "<br/><br/>"), ss["Body"]))
    story.append(Paragraph(
        "Written by Claude from the computed numbers." if narrative_source == "claude"
        else "Template summary (no Claude API key set).", ss["Small"]))

    story.append(Paragraph("Angular closure", ss["H"]))
    if cl.angular_misclosure_sec is None:
        story.append(Paragraph(cl.sum_theoretical_note, ss["Body"]))
    else:
        story.append(Paragraph(
            f"{cl.sum_theoretical_note} Misclosure {fmt_seconds(cl.angular_misclosure_sec)}, allowable "
            f"3 x {inp.sigma_angle_sec:g}\" x sqrt({cl.n}) = {cl.allowable_angular_sec:.0f}\". "
            f"Correction per angle {fmt_seconds(cl.angle_correction_sec, 2)}.", ss["Body"]))
    angle_head = "Azimuth" if inp.angle_mode == "azimuth" else f"Angle {inp.angle_mode}"
    rows = [["Station", angle_head, "Balanced", "Course", "Azimuth", "Bearing", f"Distance ({u})"]]
    for i in range(cl.n):
        rows.append([cl.names[i], fmt_dms(cl.measured_angles[i]), fmt_dms(cl.balanced_angles[i], 1),
                     cl.course_label(i), fmt_azimuth(cl.azimuths[i], 1), fmt_bearing(cl.azimuths[i], 1),
                     f"{cl.distances[i]:,.3f}"])
    story.append(_table(rows))

    story.append(Paragraph("Latitudes, departures and compass rule", ss["H"]))
    comp = res.compass
    rows = [["Course", "Latitude", "Departure", "Corr. lat", "Corr. dep", "Adj. distance", "Adj. bearing"]]
    for i in range(cl.n):
        rows.append([cl.course_label(i), f"{cl.lats[i]:,.3f}", f"{cl.deps[i]:,.3f}", f"{comp.corr_lat[i]:+.4f}",
                     f"{comp.corr_dep[i]:+.4f}", f"{comp.adj_distances[i]:,.3f}", fmt_bearing(comp.adj_azimuths[i])])
    rows.append(["Sum", f"{cl.sum_lat:+.4f}", f"{cl.sum_dep:+.4f}", f"{-cl.sum_lat:+.4f}", f"{-cl.sum_dep:+.4f}",
                 f"{cl.perimeter:,.3f}", ""])
    story.append(_table(rows))
    story.append(Paragraph(
        f"Linear misclosure = sqrt({cl.sum_lat:.4f}² + {cl.sum_dep:.4f}²) = {cl.linear_misclosure:.4f} {u} toward "
        f"{fmt_bearing(cl.misclosure_azimuth)}. Precision = {cl.perimeter:,.3f} / {cl.linear_misclosure:.4f} = "
        f"{prec}.", ss["Body"]))

    story.append(Paragraph("Adjusted coordinates", ss["H"]))
    rows = [["Station", "Compass N", "Compass E", "Transit N", "Transit E", "LSQ N", "LSQ E"]]
    for name in cl.names:
        c, t, q = res.compass.coords[name], res.transit.coords[name], ls.adjustment.coords[name]
        rows.append([name] + [f"{v:,.3f}" for v in (*c, *t, *q)])
    story.append(_table(rows))
    story.append(Paragraph(
        f"Area by coordinates ({res.chosen.method}): {res.area_text()}. Compass {res.compass.area:,.1f}, "
        f"transit {res.transit.area:,.1f}, least squares {ls.adjustment.area:,.1f} sq {u}.", ss["Body"]))

    story.append(Paragraph("Least squares adjustment", ss["H"]))
    story.append(Paragraph(
        f"Weights from sigma angle {inp.sigma_angle_sec:g}\" and sigma distance {inp.sigma_dist_const:g} {u} + "
        f"{inp.sigma_dist_ppm:g} ppm. {cl.names[0]} held fixed"
        + ("" if inp.angle_mode == "azimuth" else f" with the direction of {cl.course_label(0)}")
        + f". Converged in {ls.iterations} iterations. Redundancy {ls.redundancy}, reference variance "
        f"{ls.reference_variance:.3f} (sigma0 {ls.reference_std:.3f}). Chi-square test at 95%: "
        f"{ls.chi2_low / max(ls.redundancy, 1):.3f} to {ls.chi2_high / max(ls.redundancy, 1):.3f}, "
        f"{'passes' if ls.chi2_passes else 'fails'}. Standardized residuals over 3.29 are flagged.", ss["Body"]))
    rows = [["Observation", "Observed", "Residual", "Std. residual", "Redundancy", "Flag"]]
    for o in ls.observations:
        if o.kind == "fixed_azimuth":
            continue
        observed = f"{o.value:,.3f}" if o.kind == "distance" else fmt_dms(o.value)
        resid = f"{o.residual:+.4f}" if o.kind == "distance" else fmt_seconds(o.residual)
        rows.append([o.label, observed, resid, f"{o.std_residual:+.2f}", f"{o.redundancy:.2f}",
                     "BLUNDER?" if o.flagged else ""])
    story.append(_table(rows))
    story.append(Spacer(1, 6))
    rows = [["Station", f"Sigma N ({u})", f"Sigma E ({u})", "Semi-major", "Semi-minor", "Major axis az."]]
    for el in ls.ellipses:
        rows.append([el.station, f"{el.sigma_n:.4f}", f"{el.sigma_e:.4f}", f"{el.semi_major:.4f}",
                     f"{el.semi_minor:.4f}", "fixed" if el.semi_major == 0 else fmt_azimuth(el.major_azimuth)])
    story.append(Paragraph("Standard error ellipses (scaled by the reference variance)", ss["Body"]))
    story.append(_table(rows))

    if res.finding.candidates:
        story.append(Paragraph("Blunder search", ss["H"]))
        unit = '"' if res.finding.kind == "angle" else f" {u}"
        rows = [["Candidate", "Fix", f"Misclosure left ({u})", "Precision after"]]
        for c in res.finding.candidates:
            fix = fmt_seconds(c.correction) if res.finding.kind == "angle" else f"{c.correction:+.3f}{unit}"
            pa = "perfect" if math.isinf(c.precision_after) else f"1:{c.precision_after:,.0f}"
            rows.append([c.label, fix, f"{c.remaining_misclosure:.3f}", pa])
        story.append(_table(rows))

    story.append(PageBreak())
    story.append(Paragraph("Plan", ss["H"]))
    story.append(Image(io.BytesIO(plan_png(res, width_in=7.0, dpi=150)), width=7.0 * inch, height=5.95 * inch))
    for note in res.notes:
        story.append(Paragraph(note, ss["Small"]))

    if inp.sideshots or len(res.points) > cl.n:
        story.append(Paragraph(f"Point list (from the {res.chosen.method.lower()} coordinates)", ss["H"]))
        rows = [["Point", "Northing", "Easting", "Code", "Layer", "Description"]]
        for p in res.points:
            rows.append([p.name, f"{p.n:,.3f}", f"{p.e:,.3f}", p.code.raw, p.code.layer, p.description[:30]])
        story.append(_table(rows, align_right_from=1))
        if res.unknown_codes:
            story.append(Paragraph(
                "Codes not in the library: " + "; ".join(
                    f"{k} (closest: {v})" if v else k for k, v in res.unknown_codes.items()), ss["Small"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph(DISCLAIMER, ss["Small"]))
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title="Traverse Closure Report", author=f"Traverse Doctor v{__version__}")
    doc.build(story)
