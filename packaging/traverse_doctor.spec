# PyInstaller spec: single-file windowed exe.
# Run from the repo root:  pyinstaller packaging/traverse_doctor.spec
import glob
import os

from PyInstaller.utils.hooks import collect_data_files

# The spec runs with its own directory as the working directory, so point at
# the example CSVs directly; collect_data_files() cannot see the package from here.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [(p, "traverse_doctor/examples") for p in glob.glob(os.path.join(ROOT, "traverse_doctor", "examples", "*.csv"))]
datas += collect_data_files("ezdxf")

a = Analysis(
    [os.path.join(ROOT, "traverse_doctor", "__main__.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["traverse_doctor.ui.main_window", "traverse_doctor.report", "traverse_doctor.dxf"],
    excludes=["tkinter", "gi", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "anthropic"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TraverseDoctor",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
