"""PyInstaller entry point for pytodo-qt."""

import runpy
import sys

# Run as module to preserve package structure for relative imports
sys.argv[0] = "pytodo-qt"
runpy.run_module("pytodo_qt", run_name="__main__", alter_sys=True)
