# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Windows build.

    pyinstaller --clean --noconfirm packaging/gamecenter.spec

Produces dist/GameCenter.exe — one file, no console window. The UI is bundled
inside; app.py finds it through sys._MEIPASS (see resource_dir()).
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "ui"), "ui")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GameCenter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no black window when double-clicked
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "gamecenter.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
