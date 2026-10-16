# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm --clean desktop/rngn-media.spec  (Windows and macOS)
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
VERSION = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "rngn" / "__init__.py").read_text(encoding="utf-8")).group(1)

datas = [(str(ROOT / "ui" / name), "ui") for name in ("index.html", "app.css", "app.js")]
datas += [(str(ROOT / "assets" / name), "assets") for name in ("rngn-media.ico", "rngn-media.png")]
binaries = []
hiddenimports = []
packages = ["faster_whisper", "ctranslate2", "av", "webview", "py7zr"]
if sys.platform == "win32":
    packages += ["clr_loader", "pythonnet"]
for package in packages:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
icon = str(ROOT / "assets" / ("rngn-media.ico" if sys.platform == "win32" else "rngn-media.png"))
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="RNGN Media",
    console=False,
    icon=icon,
    upx=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas, name="RNGN Media", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="RNGN Media.app",
        icon=icon,
        bundle_identifier="com.rngn.media",
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
