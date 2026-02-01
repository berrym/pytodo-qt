# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for pytodo-qt.

This spec file builds a directory-based executable (onedir mode) with:
- Platform-specific icons
- All PyQt6 plugins
- Package data (icons)
"""

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Detect platform for icon selection
if sys.platform == "darwin":
    icon_file = "src/pytodo_qt/gui/icons/pytodo-qt.icns"
elif sys.platform == "win32":
    icon_file = "src/pytodo_qt/gui/icons/pytodo-qt.ico"
else:
    icon_file = None  # Linux doesn't use icon in executable

# Collect all pytodo_qt submodules
pytodo_qt_imports = collect_submodules("pytodo_qt")

# Collect package data (icons only - styles are in Python code)
datas = [
    ("src/pytodo_qt/gui/icons/*.svg", "pytodo_qt/gui/icons"),
]

# Hidden imports for PyQt6 plugins
hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "qasync",
] + pytodo_qt_imports

# Exclude Qt modules we don't need (prevents problematic permission plugins on macOS)
excludes = [
    "PyQt6.QtPositioning",
    "PyQt6.QtLocation",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtSensors",
    "PyQt6.QtWebEngine",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
]

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Filter out macOS permission plugins that crash when bundle info is unavailable
if sys.platform == "darwin":
    a.binaries = [
        (name, path, type_)
        for name, path, type_ in a.binaries
        if "permissionplugin" not in name.lower()
    ]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir mode: binaries collected separately
    name="pytodo-qt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowed mode, no terminal
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",  # Required for Qt on macOS
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="pytodo-qt",
)

# macOS app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="pytodo-qt.app",
        icon=icon_file,
        bundle_identifier="com.pytodo-qt.app",
        info_plist={
            "CFBundleDisplayName": "PyTodo-Qt",
            "CFBundleExecutable": "pytodo-qt",
            "CFBundleShortVersionString": "0.3.5",
            "CFBundleVersion": "0.3.5",
            "CFBundlePackageType": "APPL",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13",
        },
    )
