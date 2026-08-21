# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the unsigned macOS preview artifact.

The Windows spec keeps its native icon and collection layout.  This file is
kept separate so path separators, the application bundle, and optional ASR
dependencies do not leak platform assumptions into the Windows release.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.building.datastruct import Tree


datas = [
    ("backend/requirements.txt", "backend"),
    ("backend/requirements.desktop.txt", "backend"),
    ("backend/requirements.deploy.txt", "backend"),
]
binaries = []
hiddenimports = ["app.main"]
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("uvicorn")

for optional_package in ("webview", "imageio_ffmpeg", "faster_whisper"):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(optional_package)
    except ImportError:
        package_datas, package_binaries, package_hiddenimports = [], [], []
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    ["desktop/main.py"],
    pathex=["backend"],
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
a.datas += Tree("backend/app", prefix="backend/app", excludes=["__pycache__", "*.pyc"])
a.datas += Tree("web", prefix="web", excludes=["tests", "tests/*"])
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LearnNote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

BUNDLE(
    exe,
    name="LearnNote.app",
    bundle_identifier="tech.hurry060215.learnnote",
)
