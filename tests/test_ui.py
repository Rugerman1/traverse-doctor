import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_runs_examples_and_renders():
    from PySide6.QtWidgets import QApplication

    from traverse_doctor.fileio import example_path
    from traverse_doctor.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    assert win.res is not None and win.res.passes
    assert win.coords.rowCount() == 17
    assert not win.plan.pixmap().isNull()
    assert win.codes.rowCount() == 1  # HYD
    win.apply_codes()  # accepts the suggestion HYD -> FH
    assert win.res.unknown_codes == {}
    win.method.setCurrentIndex(2)  # least squares
    assert win.res.method == "lsq" and win.lsq.rowCount() == 10
    win.load_file(example_path("angle-blunder.csv"))
    assert win.res.finding.kind == "angle" and "station C" in win.finding.text()
    # the inputs survive a trip through the table
    again = win.read_inputs()
    assert [round(s.angle, 6) for s in again.stations] == [round(s.angle, 6) for s in win.res.inp.stations]
    app.processEvents()
