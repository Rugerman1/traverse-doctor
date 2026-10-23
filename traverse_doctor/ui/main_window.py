"""PySide6 main window."""

from __future__ import annotations

import math
import os
import sys
import tempfile
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .. import __version__
from ..angles import fmt_azimuth, fmt_bearing, fmt_dms, fmt_seconds, parse_angle, parse_direction
from ..codes import LIBRARY
from ..engine import METHODS, Result, run, summary_dict
from ..fileio import EXAMPLE_FILES, coordinates_csv, example_path, load_csv, write_csv
from ..model import Sideshot, Station, TraverseInput
from ..narrative import api_key, map_codes_with_claude, save_api_key, write_narrative
from ..plots import plan_png

ANGLE_MODES = [("Angles right (interior angles, loop runs counterclockwise)", "right"),
               ("Angles left (interior angles, loop runs clockwise)", "left"),
               ("Azimuth or bearing for each course", "azimuth")]
METHOD_NAMES = ["Compass rule", "Transit rule", "Least squares"]
TRAV_COLUMNS = ["Station", "Angle (D-M-S)", "Distance", "Code", "Description"]
SS_COLUMNS = ["Point", "From", "BS", "Angle right", "Distance", "Code", "Description"]
GREEN, RED = "#1a7f37", "#b42318"


class ExportWorker(QThread):
    done = Signal(str, str)
    failed = Signal(str)

    def __init__(self, res: Result, path: str):
        super().__init__()
        self.res = res
        self.path = path

    def run(self):
        try:
            from ..report import build_pdf

            narrative, source = write_narrative(summary_dict(self.res))
            build_pdf(self.res, narrative, source, self.path)
            self.done.emit(self.path, source)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())


def _spin(lo, hi, value, step=1.0, decimals=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    return s


def _table(columns, stretch_last=True):
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.verticalHeader().setVisible(False)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Interactive)
    h.setStretchLastSection(stretch_last)
    return t


def _ro_table(columns):
    t = _table(columns)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return t


def _set_row(table, values):
    r = table.rowCount()
    table.insertRow(r)
    for c, v in enumerate(values):
        table.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
    return r


def _dms_cell(deg: float) -> str:
    text = fmt_dms(deg, 1)
    d, rest = text.split("°")
    m, s = rest.split("'")
    s = s.rstrip('"')
    return f"{d}-{m}-{s[:-2] if s.endswith('.0') else s}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Traverse Doctor {__version__}")
        self.resize(1360, 860)
        self.res: Result | None = None
        self.worker: ExportWorker | None = None
        self.aliases: dict[str, str] = {}
        self._build_menu()
        self._build_ui()
        self.load_file(example_path("site-loop.csv"))

    # ---------- layout ----------
    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        for text, slot, key in [("Open traverse CSV...", self.open_csv, "Ctrl+O"),
                                ("Save traverse CSV...", self.save_csv, "Ctrl+S")]:
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
        ex = m.addMenu("Open example")
        for label, fname in EXAMPLE_FILES.items():
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, f=fname: self.load_file(example_path(f)))
            ex.addAction(a)
        m.addSeparator()
        for text, slot, key in [("Export PDF closure report...", self.export_pdf, "Ctrl+E"),
                                ("Export DXF for CAD...", self.export_dxf, "Ctrl+D"),
                                ("Export point file (P,N,E,Z,D)...", self.export_points, "")]:
            a = QAction(text, self)
            if key:
                a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        q = QAction("Quit", self)
        q.triggered.connect(self.close)
        m.addAction(q)
        s = self.menuBar().addMenu("&Settings")
        k = QAction("Claude API key...", self)
        k.triggered.connect(self.set_api_key)
        s.addAction(k)
        h = self.menuBar().addMenu("&Help")
        f = QAction("CSV format", self)
        f.triggered.connect(self.csv_help)
        h.addAction(f)
        a = QAction("About", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_inputs())
        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 800])
        self.setCentralWidget(splitter)

    def _build_inputs(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        meta = QGroupBox("Project")
        form = QFormLayout(meta)
        self.project = QLineEdit()
        self.party = QLineEdit()
        self.date = QLineEdit()
        form.addRow("Project", self.project)
        form.addRow("Party chief", self.party)
        form.addRow("Date", self.date)
        layout.addWidget(meta)

        setup = QGroupBox("Setup")
        form = QFormLayout(setup)
        start = QHBoxLayout()
        self.start_n = _spin(-1e8, 1e8, 5000, 100, 3)
        self.start_e = _spin(-1e8, 1e8, 5000, 100, 3)
        start.addWidget(QLabel("N"))
        start.addWidget(self.start_n)
        start.addWidget(QLabel("E"))
        start.addWidget(self.start_e)
        form.addRow("First station", start)
        self.start_dir = QLineEdit()
        self.start_dir.setPlaceholderText("S 49 19 13 E  or  130-40-47")
        self.start_dir.setToolTip("Bearing or azimuth of the first course (station 1 to station 2).")
        form.addRow("First course direction", self.start_dir)
        self.mode = QComboBox()
        for label, _ in ANGLE_MODES:
            self.mode.addItem(label)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Angles", self.mode)
        self.units = QComboBox()
        self.units.addItems(["Feet", "Meters"])
        form.addRow("Units", self.units)
        sig = QHBoxLayout()
        self.sig_a = _spin(0.1, 120, 5, 1, 1, '"')
        self.sig_d = _spin(0, 10, 0.01, 0.005, 3)
        self.sig_ppm = _spin(0, 100, 3, 1, 1, " ppm")
        sig.addWidget(QLabel("Angle"))
        sig.addWidget(self.sig_a)
        sig.addWidget(QLabel("Distance"))
        sig.addWidget(self.sig_d)
        sig.addWidget(self.sig_ppm)
        form.addRow("Std. deviations", sig)
        self.required = _spin(500, 1e6, 10000, 1000, 0)
        self.required.setPrefix("1 : ")
        form.addRow("Required precision", self.required)
        self.method = QComboBox()
        self.method.addItems(METHOD_NAMES)
        self.method.currentIndexChanged.connect(lambda _: self.res and self.run())
        form.addRow("Coordinates from", self.method)
        layout.addWidget(setup)

        tabs = QTabWidget()
        self.trav = _table(TRAV_COLUMNS)
        self.ss = _table(SS_COLUMNS)
        for t, cols in ((self.trav, TRAV_COLUMNS), (self.ss, SS_COLUMNS)):
            w = QWidget()
            v = QVBoxLayout(w)
            v.addWidget(t)
            row = QHBoxLayout()
            add = QPushButton("Add row")
            add.clicked.connect(lambda _=False, tt=t, n=len(cols): _set_row(tt, [""] * n))
            rem = QPushButton("Remove selected")
            rem.clicked.connect(lambda _=False, tt=t: self._remove_rows(tt))
            row.addWidget(add)
            row.addWidget(rem)
            row.addStretch()
            v.addLayout(row)
            tabs.addTab(w, "Traverse" if t is self.trav else "Side shots")
        layout.addWidget(tabs, 1)

        buttons = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.run_btn.clicked.connect(self.run)
        self.pdf_btn = QPushButton("PDF report")
        self.pdf_btn.clicked.connect(self.export_pdf)
        self.dxf_btn = QPushButton("DXF")
        self.dxf_btn.clicked.connect(self.export_dxf)
        self.pts_btn = QPushButton("Point file")
        self.pts_btn.clicked.connect(self.export_points)
        for b in (self.run_btn, self.pdf_btn, self.dxf_btn, self.pts_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(520)
        return scroll

    def _build_results(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.verdict = QLabel("Open a traverse and press Run.")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.verdict.setFont(f)
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)
        self.finding = QLabel("")
        self.finding.setWordWrap(True)
        self.finding.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.finding)

        self.tabs = QTabWidget()
        self.plan = QLabel("")
        self.plan.setAlignment(Qt.AlignCenter)
        plan_scroll = QScrollArea()
        plan_scroll.setWidget(self.plan)
        plan_scroll.setWidgetResizable(True)
        self.tabs.addTab(plan_scroll, "Plan")
        self.closure_text = QTextEdit()
        self.closure_text.setReadOnly(True)
        self.closure_text.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.closure_text, "Closure")
        self.coords = _ro_table(["Point", "Northing", "Easting", "Code", "Layer", "Description"])
        self.tabs.addTab(self.coords, "Coordinates")
        self.lsq = _ro_table(["Observation", "Observed", "Residual", "Std. residual", "Redundancy", "Flag"])
        self.tabs.addTab(self.lsq, "Least squares")

        codes = QWidget()
        v = QVBoxLayout(codes)
        v.addWidget(QLabel("Codes that are not in the library go to their own layer. Map them to a library code "
                           "and press Apply. The suggestion is the closest spelling."))
        self.codes = _table(["Code", "Points", "Map to"])
        v.addWidget(self.codes)
        row = QHBoxLayout()
        apply_btn = QPushButton("Apply mapping")
        apply_btn.clicked.connect(self.apply_codes)
        self.ask_btn = QPushButton("Ask Claude to map codes")
        self.ask_btn.clicked.connect(self.ask_claude_codes)
        row.addWidget(apply_btn)
        row.addWidget(self.ask_btn)
        row.addStretch()
        v.addLayout(row)
        self.tabs.addTab(codes, "Codes")
        layout.addWidget(self.tabs, 1)
        return panel

    # ---------- inputs ----------
    def _mode_changed(self, idx):
        azimuth_mode = ANGLE_MODES[idx][1] == "azimuth"
        self.start_dir.setEnabled(not azimuth_mode)
        self.trav.setHorizontalHeaderItem(1, QTableWidgetItem("Azimuth or bearing" if azimuth_mode else "Angle (D-M-S)"))

    def _remove_rows(self, table):
        for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(r)

    def _text(self, table, r, c) -> str:
        item = table.item(r, c)
        return item.text().strip() if item else ""

    def set_inputs(self, inp: TraverseInput):
        self.project.setText(inp.project)
        self.party.setText(inp.party_chief)
        self.date.setText(inp.date)
        self.start_n.setValue(inp.start_n)
        self.start_e.setValue(inp.start_e)
        self.start_dir.setText(fmt_bearing(inp.start_azimuth, 1).replace("°", " ").replace("'", " ").replace('"', ""))
        self.mode.setCurrentIndex([m for _, m in ANGLE_MODES].index(inp.angle_mode))
        self.units.setCurrentIndex(0 if inp.units == "ft" else 1)
        self.sig_a.setValue(inp.sigma_angle_sec)
        self.sig_d.setValue(inp.sigma_dist_const)
        self.sig_ppm.setValue(inp.sigma_dist_ppm)
        self.required.setValue(inp.required_precision)
        self.trav.setRowCount(0)
        for s in inp.stations:
            ang = fmt_bearing(s.angle, 1) if inp.angle_mode == "azimuth" else _dms_cell(s.angle)
            _set_row(self.trav, [s.name, ang, f"{s.distance:.3f}", s.code, s.description])
        self.ss.setRowCount(0)
        for s in inp.sideshots:
            _set_row(self.ss, [s.name, s.occupied, s.backsight, _dms_cell(s.angle), f"{s.distance:.3f}", s.code,
                               s.description])
        self.trav.resizeColumnsToContents()
        self.ss.resizeColumnsToContents()

    def read_inputs(self) -> TraverseInput:
        mode = ANGLE_MODES[self.mode.currentIndex()][1]
        stations = []
        for r in range(self.trav.rowCount()):
            name = self._text(self.trav, r, 0)
            if not name:
                continue
            where = f"Traverse row {r + 1} ({name})"
            try:
                ang = self._text(self.trav, r, 1)
                value = parse_direction(ang) if mode == "azimuth" else parse_angle(ang)
                stations.append(Station(name, value, float(self._text(self.trav, r, 2)),
                                        self._text(self.trav, r, 3), self._text(self.trav, r, 4)))
            except ValueError as exc:
                raise ValueError(f"{where}: {exc}") from None
        shots = []
        for r in range(self.ss.rowCount()):
            name = self._text(self.ss, r, 0)
            if not name:
                continue
            try:
                shots.append(Sideshot(name, self._text(self.ss, r, 1), parse_angle(self._text(self.ss, r, 3)),
                                      float(self._text(self.ss, r, 4)), self._text(self.ss, r, 5),
                                      self._text(self.ss, r, 6), self._text(self.ss, r, 2)))
            except ValueError as exc:
                raise ValueError(f"Side shot row {r + 1} ({name}): {exc}") from None
        start = 0.0 if mode == "azimuth" else parse_direction(self.start_dir.text() or "0")
        return TraverseInput(
            stations=stations, sideshots=shots, start_n=self.start_n.value(), start_e=self.start_e.value(),
            start_azimuth=start, angle_mode=mode, units="ft" if self.units.currentIndex() == 0 else "m",
            sigma_angle_sec=self.sig_a.value(), sigma_dist_const=self.sig_d.value(),
            sigma_dist_ppm=self.sig_ppm.value(), required_precision=self.required.value(),
            project=self.project.text(), party_chief=self.party.text(), date=self.date.text(),
        )

    # ---------- actions ----------
    def load_file(self, path: str):
        try:
            inp = load_csv(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Couldn't open the file", str(exc))
            return
        self.aliases = {}
        self.set_inputs(inp)
        self.run()

    def open_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open traverse", "", "CSV files (*.csv *.txt);;All files (*)")
        if path:
            self.load_file(path)

    def save_csv(self):
        try:
            inp = self.read_inputs()
        except ValueError as exc:
            QMessageBox.warning(self, "Check the inputs", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save traverse", (inp.project or "traverse") + ".csv",
                                              "CSV files (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(write_csv(inp))

    def run(self):
        try:
            inp = self.read_inputs()
            self.res = run(inp, METHODS[self.method.currentIndex()], self.aliases)
        except (ValueError, KeyError, ZeroDivisionError, ArithmeticError) as exc:
            QMessageBox.warning(self, "Check the inputs", str(exc))
            self.res = None
            return
        except Exception as exc:  # noqa: BLE001  (singular least squares and the like)
            QMessageBox.warning(self, "Couldn't adjust this traverse", f"{type(exc).__name__}: {exc}")
            self.res = None
            return
        self.show_results(self.res)

    def show_results(self, res: Result):
        cl, inp, ls = res.closure, res.inp, res.lsq
        u = inp.unit_label
        prec = "perfect closure" if math.isinf(cl.precision) else f"1:{cl.precision:,.0f}"
        if res.passes:
            self.verdict.setText(f"Closes at {prec}. Meets 1:{inp.required_precision:,.0f}.")
            self.verdict.setStyleSheet(f"color: {GREEN};")
        else:
            self.verdict.setText(f"Precision {prec}. Does not meet 1:{inp.required_precision:,.0f}.")
            self.verdict.setStyleSheet(f"color: {RED};")
        text = f"<b>{res.finding.headline}</b>"
        if res.finding.kind != "none":
            text += "<br>" + res.finding.detail
        for w in res.warnings:
            text += f"<br><span style='color:{RED}'>Warning: {w}</span>"
        self.finding.setText(text)

        pix = QPixmap()
        pix.loadFromData(plan_png(res, width_in=7.6, dpi=95))
        self.plan.setPixmap(pix)

        lines = []
        if cl.angular_misclosure_sec is not None:
            lines += [cl.sum_theoretical_note,
                      f"Angular misclosure {fmt_seconds(cl.angular_misclosure_sec)}, allowable "
                      f"{cl.allowable_angular_sec:.0f}\", correction per angle {fmt_seconds(cl.angle_correction_sec, 2)}", ""]
        lines.append(f"{'Course':<9}{'Azimuth':>15}{'Bearing':>19}{'Distance':>12}{'Latitude':>13}{'Departure':>13}")
        for i in range(cl.n):
            lines.append(f"{cl.course_label(i):<9}{fmt_azimuth(cl.azimuths[i], 1):>15}{fmt_bearing(cl.azimuths[i]):>19}"
                         f"{cl.distances[i]:>12.3f}{cl.lats[i]:>13.3f}{cl.deps[i]:>13.3f}")
        lines.append(f"{'Sum':<9}{'':>15}{'':>19}{cl.perimeter:>12.3f}{cl.sum_lat:>13.4f}{cl.sum_dep:>13.4f}")
        lines += ["", f"Linear misclosure {cl.linear_misclosure:.4f} {u} toward {fmt_bearing(cl.misclosure_azimuth)}",
                  f"Precision {prec}", f"Area ({res.chosen.method}): {res.area_text()}", ""]
        lines.append(f"Least squares: redundancy {ls.redundancy}, reference variance {ls.reference_variance:.3f}, "
                     f"chi-square {'passes' if ls.chi2_passes else 'fails'}, {ls.iterations} iterations")
        for el in ls.ellipses[1:]:
            lines.append(f"  {el.station}: error ellipse {el.semi_major:.4f} x {el.semi_minor:.4f} {u}, "
                         f"major axis {fmt_azimuth(el.major_azimuth)}")
        lines += [""] + res.notes
        self.closure_text.setPlainText("\n".join(lines))

        self.coords.setRowCount(0)
        for p in res.points:
            _set_row(self.coords, [p.name, f"{p.n:,.3f}", f"{p.e:,.3f}", p.code.raw, p.code.layer, p.description])
        self.lsq.setRowCount(0)
        for o in ls.observations:
            if o.kind == "fixed_azimuth":
                continue
            r = _set_row(self.lsq, [
                o.label, f"{o.value:,.3f}" if o.kind == "distance" else fmt_dms(o.value),
                f"{o.residual:+.4f}" if o.kind == "distance" else fmt_seconds(o.residual),
                f"{o.std_residual:+.2f}", f"{o.redundancy:.2f}", "BLUNDER?" if o.flagged else ""])
            if o.flagged:
                self.lsq.item(r, 5).setForeground(QColor(RED))

        self.codes.setRowCount(0)
        counts = {}
        for p in res.points:
            if not p.code.known and p.code.code:
                counts[p.code.code] = counts.get(p.code.code, 0) + 1
        for code, suggestion in res.unknown_codes.items():
            r = _set_row(self.codes, [code, str(counts.get(code, 0)), ""])
            box = QComboBox()
            box.addItem("(keep as its own layer)")
            for key, (_, desc, _, _) in LIBRARY.items():
                box.addItem(f"{key}  {desc}", key)
            if suggestion:
                box.setCurrentIndex(list(LIBRARY).index(suggestion) + 1)
            self.codes.setCellWidget(r, 2, box)
        self.codes.resizeColumnsToContents()
        self.tabs.setTabText(4, f"Codes ({len(res.unknown_codes)})" if res.unknown_codes else "Codes")

    def apply_codes(self):
        for r in range(self.codes.rowCount()):
            code = self._text(self.codes, r, 0)
            key = self.codes.cellWidget(r, 2).currentData()
            if key:
                self.aliases[code] = key
            else:
                self.aliases.pop(code, None)
        self.run()

    def ask_claude_codes(self):
        if not api_key():
            QMessageBox.information(self, "Claude", "Set a Claude API key under Settings first.")
            return
        codes = [self._text(self.codes, r, 0) for r in range(self.codes.rowCount())]
        mapping = map_codes_with_claude(codes)
        if mapping is None:
            QMessageBox.warning(self, "Claude", "The request failed. The spelling suggestions are still shown.")
            return
        for r in range(self.codes.rowCount()):
            key = mapping.get(self._text(self.codes, r, 0))
            box = self.codes.cellWidget(r, 2)
            box.setCurrentIndex(list(LIBRARY).index(key) + 1 if key else 0)

    def _ensure_result(self) -> bool:
        if self.res is None:
            self.run()
        return self.res is not None

    def _default_name(self, ext):
        return f"{(self.res.inp.project or 'traverse').replace(' ', '_')}.{ext}"

    def export_pdf(self):
        if not self._ensure_result():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save closure report", self._default_name("pdf"), "PDF files (*.pdf)")
        if not path:
            return
        self.pdf_btn.setEnabled(False)
        self.pdf_btn.setText("Writing" + (" (asking Claude)..." if api_key() else "..."))
        self.worker = ExportWorker(self.res, path)
        self.worker.done.connect(self._export_done)
        self.worker.failed.connect(self._export_failed)
        self.worker.start()

    def _export_done(self, path, source):
        self.pdf_btn.setEnabled(True)
        self.pdf_btn.setText("PDF report")
        note = "Summary written by Claude." if source == "claude" else (
            "Summary used the built-in template (no Claude API key set, or the request failed).")
        QMessageBox.information(self, "Report saved", f"Saved to:\n{path}\n\n{note}")
        _open(path)

    def _export_failed(self, text):
        self.pdf_btn.setEnabled(True)
        self.pdf_btn.setText("PDF report")
        QMessageBox.critical(self, "Export failed", text)

    def export_dxf(self):
        if not self._ensure_result():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save DXF", self._default_name("dxf"), "DXF files (*.dxf)")
        if path:
            from ..dxf import save_dxf

            save_dxf(self.res, path)
            QMessageBox.information(self, "DXF saved", f"Saved to:\n{path}\n\nLayers: one per feature code, plus "
                                    "V-CTRL-TRAV (adjusted loop) and V-CTRL-TRAV-RAW (unadjusted, dashed).")

    def export_points(self):
        if not self._ensure_result():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save point file", self._default_name("csv").replace(".csv", "-points.csv"),
                                              "CSV files (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(coordinates_csv(self.res))

    def set_api_key(self):
        key, ok = QInputDialog.getText(
            self, "Claude API key",
            "Paste an Anthropic API key to have Claude write the report summary and map odd field codes.\n"
            "Leave blank to work fully offline. Stored in %APPDATA%\\TraverseDoctor.",
            QLineEdit.Password, api_key() or "",
        )
        if ok:
            save_api_key(key)

    def csv_help(self):
        from .. import fileio

        box = QMessageBox(self)
        box.setWindowTitle("Traverse CSV format")
        box.setText("One row per traverse station (Type TRAV) or side shot (Type SS). Open an example from the "
                    "File menu to see a complete file.")
        box.setDetailedText(fileio.__doc__)
        box.exec()

    def about(self):
        QMessageBox.about(
            self, "About Traverse Doctor",
            f"<b>Traverse Doctor {__version__}</b><br>"
            "Closed traverse closure, compass, transit and least squares adjustment, blunder finding, "
            "and DXF output with coded linework.<br><br>"
            "Student-built tool for checking traverse computations. Not for boundary or construction work.",
        )


def _open(path):
    if sys.platform == "win32":
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            pass


def selftest() -> int:
    """Headless check used by the packaged exe in CI.  It exercises what the
    bundle has to carry (Qt, matplotlib, ezdxf, ReportLab, the examples, the
    solver) and leaves through os._exit so that Qt teardown, which can fault
    on Windows after the check has already passed, never turns a good build
    into a failed one."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ok = False
    try:
        from ..dxf import build_dxf
        from ..narrative import template_narrative
        from ..report import build_pdf

        app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
        kinds = {}
        for fname in EXAMPLE_FILES.values():
            res = run(load_csv(example_path(fname)), "lsq")
            kinds[fname] = res.finding.kind
        pix = QPixmap()
        pix.loadFromData(plan_png(res, width_in=6.0, dpi=60))
        doc = build_dxf(res)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "selftest.pdf")
            build_pdf(res, template_narrative(summary_dict(res)), "template", pdf)
            pdf_ok = os.path.getsize(pdf) > 10_000
        ok = (kinds == {"site-loop.csv": "none", "angle-blunder.csv": "angle", "distance-blunder-raw.csv": "distance"}
              and not pix.isNull() and len(doc.modelspace()) > 5 and pdf_ok)
        print("selftest", kinds, "ok" if ok else "FAILED")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    os._exit(0 if ok else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    app = QApplication(sys.argv)
    app.setApplicationName("Traverse Doctor")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
