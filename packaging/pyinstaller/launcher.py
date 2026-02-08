"""PyInstaller entry point for pytodo-qt."""

import os
import sys

# CRITICAL: Disable the native macOS permission plugins that cause crashes
# with PyQt6 6.5+ when running as a PyInstaller bundle
os.environ["QT_APPLE_DISABLE_PROMPT_ANSWERER"] = "1"

import runpy

# Run as module to preserve package structure for relative imports
sys.argv[0] = "pytodo-qt"
runpy.run_module("pytodo_qt", run_name="__main__", alter_sys=True)
