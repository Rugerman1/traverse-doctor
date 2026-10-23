"""Plan view of the traverse rendered with matplotlib."""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse as EllipsePatch  # noqa: E402

from .engine import Result  # noqa: E402

ADJ = "#1f4e9c"
RAW = "#c2410c"


def plan_png(res: Result, width_in: float = 7.0, dpi: int = 150, show_ellipses: bool = True) -> bytes:
    cl, inp = res.closure, res.inp
    coords = res.chosen.coords
    fig, ax = plt.subplots(figsize=(width_in, width_in * 0.85))

    loop = [coords[n] for n in cl.names] + [coords[cl.names[0]]]
    ax.plot([e for _, e in loop], [n for n, _ in loop], "-", color=ADJ, lw=1.6,
            label=f"Adjusted ({res.chosen.method})")
    n_, e_ = inp.start_n, inp.start_e
    raw = [(n_, e_)]
    for lat, dep in zip(cl.lats, cl.deps):
        n_ += lat
        e_ += dep
        raw.append((n_, e_))
    ax.plot([e for _, e in raw], [n for n, _ in raw], "--", color=RAW, lw=1.0, label="Unadjusted")

    span = max(max(e for _, e in loop) - min(e for _, e in loop), max(n for n, _ in loop) - min(n for n, _ in loop))
    if cl.linear_misclosure > span * 0.002:
        ax.annotate("", xy=(raw[-1][1], raw[-1][0]), xytext=(inp.start_e, inp.start_n),
                    arrowprops=dict(arrowstyle="->", color=RAW, lw=1.2))
    ax.text(0.01, 0.01, f"Misclosure {cl.linear_misclosure:.3f} {inp.unit_label}, "
            + ("perfect closure" if math.isinf(cl.precision) else f"1:{cl.precision:,.0f}"),
            transform=ax.transAxes, fontsize=8, color=RAW)

    for p in res.points:
        if p.is_station:
            ax.plot(p.e, p.n, "^", color=ADJ, ms=7)
            ax.annotate(p.name, (p.e, p.n), textcoords="offset points", xytext=(5, 5), fontsize=9, weight="bold")
        else:
            ax.plot(p.e, p.n, "o", ms=3, color="#555555" if p.code.known else "#b42318")
            ax.annotate(f"{p.name} {p.code.code}".strip(), (p.e, p.n), textcoords="offset points",
                        xytext=(3, -8), fontsize=6, color="#555555")
    sus = res.finding.suspect
    if sus is not None:
        k = sus.index
        if res.finding.kind == "angle":
            n, e = coords[cl.names[k]]
            ax.plot(e, n, "o", ms=18, mfc="none", mec="#b42318", mew=2, label=f"Suspect: {sus.label}")
        else:
            (n1, e1), (n2, e2) = coords[cl.names[k]], coords[cl.names[(k + 1) % cl.n]]
            ax.plot([e1, e2], [n1, n2], "-", color="#b42318", lw=4, alpha=0.45, label=f"Suspect: {sus.label}")
    pts = {p.name: (p.e, p.n) for p in res.points}
    for ls in res.linework:
        xy = [pts[n] for n in ls.points] + ([pts[ls.points[0]]] if ls.closed else [])
        ax.plot([x for x, _ in xy], [y for _, y in xy], "-", lw=0.8, color="#2f855a")

    if show_ellipses and res.method == "lsq":
        big = max((e.semi_major for e in res.lsq.ellipses), default=0)
        if big > 0:
            scale = 0.04 * span / big
            for el in res.lsq.ellipses[1:]:
                n, e = coords[el.station]
                ax.add_patch(EllipsePatch((e, n), 2 * el.semi_major * scale, 2 * el.semi_minor * scale,
                                          angle=90 - el.major_azimuth, fill=False, color="#7c3aed", lw=0.9))
            ax.plot([], [], color="#7c3aed", lw=0.9, label=f"Error ellipses x{scale:,.0f}")

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel(f"Easting ({inp.unit_label})")
    ax.set_ylabel(f"Northing ({inp.unit_label})")
    ax.grid(True, lw=0.4, alpha=0.5)
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="upper right")
    ax.annotate("N", xy=(0.04, 0.93), xytext=(0.04, 0.83), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="black"), ha="center", fontsize=9, weight="bold")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
