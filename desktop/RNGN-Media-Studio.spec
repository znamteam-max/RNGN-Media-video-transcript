# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = []

for package in [
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "onnxruntime",
    "huggingface_hub",
    "requests",
    "tkinterdnd2",
    "imageio_ffmpeg",
]:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception:
        pass

for distribution in [
    "faster-whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "onnxruntime",
    "huggingface-hub",
    "requests",
    "tkinterdnd2",
    "imageio-ffmpeg",
]:
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

tools_dir = Path("vendor") / "tools"
if tools_dir.is_dir():
    for tool in tools_dir.iterdir():
        if tool.is_file():
            datas.append((str(tool), "tools"))

analysis = Analysis(
    ["unified_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="RNGN-Media-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RNGN-Media-Studio",
)
