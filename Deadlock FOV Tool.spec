# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the single-file build.

The Qt wheels ship much more than a widget app needs: a 20 MB software OpenGL
fallback, Qt Quick, PDF, translations, every image-format plugin and so on.
Everything listed below is removed from the bundle. Run tests/gui_smoke.py
after touching this file.
"""

from pathlib import Path

ROOT = Path(SPECPATH)

EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "setuptools",
    "pip",
    # Qt modules this app never imports.
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtDBus",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtDesigner",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtAxContainer",
    "PySide6.QtConcurrent",
    "PySide6.QtHttpServer",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,
)

# Qt DLLs and plugins that a plain widget window never touches. Kept as a
# second, name-based filter because Qt's own hook collection is broad.
DROP_FILES = {
    "opengl32sw.dll",          # 20 MB software OpenGL fallback
    "qt6quick.dll",
    "qt6qml.dll",
    "qt6qmlmodels.dll",
    "qt6pdf.dll",
    "qt6opengl.dll",
    "qt6network.dll",
    "qt6svg.dll",
    "qt6virtualkeyboard.dll",
    "qtnetwork.pyd",
    "qtqml.pyd",
    "qtquick.pyd",
    "qtpdf.pyd",
    "qtopengl.pyd",
    "qtsvg.pyd",
    "qtquickcontrols2.pyd",
    "qtquick3d.pyd",
    "qdirect2d.dll",           # optional platform plugin; qwindows is enough
    "qopensslbackend.dll",     # only QtNetwork would use this
}

DROP_PREFIXES = (
    "pyside6/translations/",           # English UI only
    "pyside6/plugins/imageformats/",   # PNG is built into QtGui and no images load
    "pyside6/plugins/tls/",            # HTTPS goes through Python's own ssl module
    "pyside6/plugins/virtualkeyboard/",
    "pyside6/plugins/iconengines/",
    "pyside6/plugins/networkinformation/",
)


def keep(entry) -> bool:
    destination = entry[0].replace("\\", "/").lower()
    if destination.rsplit("/", 1)[-1] in DROP_FILES:
        return False
    return not destination.startswith(DROP_PREFIXES)


a.binaries = [item for item in a.binaries if keep(item)]
a.datas = [item for item in a.datas if keep(item)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Deadlock FOV Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
