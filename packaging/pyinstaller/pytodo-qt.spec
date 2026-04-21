# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for pytodo-qt.

This spec file builds a directory-based executable (onedir mode) with:
- Platform-specific icons
- All PyQt6 plugins
- Package data (icons)
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Root of the repository (two levels up from packaging/pyinstaller/)
ROOT = os.path.normpath(os.path.join(SPECPATH, '..', '..'))

# Detect platform for icon selection
if sys.platform == "darwin":
    icon_file = os.path.join(ROOT, "src", "pytodo_qt", "gui", "icons", "pytodo-qt.icns")
elif sys.platform == "win32":
    icon_file = os.path.join(ROOT, "src", "pytodo_qt", "gui", "icons", "pytodo-qt.ico")
else:
    icon_file = None  # Linux doesn't use icon in executable

# Collect all pytodo_qt submodules
pytodo_qt_imports = collect_submodules("pytodo_qt")

# desktop-notifier dispatches to platform backends via conditional imports
# (macos / dbus / winrt / dummy) inside its main.py — PyInstaller's static
# analysis picks most of them up, but collect_submodules is the defensive
# choice and keeps builds stable if upstream adds new backends.
desktop_notifier_imports = collect_submodules("desktop_notifier")

# Collect package data — runtime assets loaded relative to __file__ via
# Path(__file__).parent lookups in gui/. The stylesheet is in Python
# code so it doesn't need bundling, but everything else loaded off disk
# must be listed here or it silently fails to resolve inside the bundle.
datas = [
    # SVG icons used throughout the UI (toolbars, buttons, inline decorations)
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "icons", "*.svg"), "pytodo_qt/gui/icons"),
    # PNG icons used for the application window icon via QIcon.addFile()
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "icons", "pytodo-qt-256.png"), "pytodo_qt/gui/icons"),
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "icons", "pytodo-qt-1024.png"), "pytodo_qt/gui/icons"),
    # Bundled Noto Sans + Noto Color Emoji registered via QFontDatabase at
    # startup. Without this, apply_bundled_font() sets QFont("Noto Sans")
    # against a font that was never registered, and Qt falls back to a
    # wider default font with visibly off metrics.
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "fonts", "*.ttf"), "pytodo_qt/gui/fonts"),
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "fonts", "OFL.txt"), "pytodo_qt/gui/fonts"),
    # Pomodoro break/work notification sounds
    (os.path.join(ROOT, "src", "pytodo_qt", "gui", "sounds", "*.wav"), "pytodo_qt/gui/sounds"),
    (os.path.join(SPECPATH, "qt.conf"), "."),  # Qt plugin path configuration
]

# Hidden imports for PyQt6 plugins. Matplotlib backends are listed
# explicitly even though PyInstaller ships a matplotlib hook that
# handles most of the bundling — the specific backend modules chart
# export imports (backend_pdf, backend_agg) are not always picked up
# automatically when the only reachable reference is a lazy import
# inside a function body (see core/chart_export.py). Listing them
# here makes the dependency tree deterministic across PyInstaller
# versions.
hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "qasync",
    "matplotlib",
    "matplotlib.figure",
    "matplotlib.dates",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_agg",
    # desktop-notifier's rubicon.objc bridge is imported lazily on macOS
    # through rubicon's proxy machinery; name it explicitly so PyInstaller
    # pulls it into the bundle.
    "rubicon.objc",
] + pytodo_qt_imports + desktop_notifier_imports

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
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, "runtime_hook_macos.py")],
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
    argv_emulation=False,  # Disabled - can cause bundle context issues on macOS
    target_arch=None,
    codesign_identity=None,  # Don't sign during build, handled in workflow
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
        bundle_identifier="com.berrym.pytodo-qt",
        info_plist={
            "CFBundleDisplayName": "PyTodo-Qt",
            "CFBundleExecutable": "pytodo-qt",
            "CFBundleName": "PyTodo-Qt",
            "CFBundleShortVersionString": "0.3.11b1",
            "CFBundleVersion": "0.3.11b1",
            "CFBundlePackageType": "APPL",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13",
            # Privacy descriptions - required for Qt permission plugins
            "NSLocationWhenInUseUsageDescription": "Required for Qt Location services.",
            "NSCameraUsageDescription": "Access needed for photos.",
            "NSMicrophoneUsageDescription": "Access needed for audio.",
            "LSEnvironment": {
                "QT_MAC_WANTS_LAYER": "1",
                "QT_APPLE_DISABLE_PROMPT_ANSWERER": "1",
            },
        },
    )
