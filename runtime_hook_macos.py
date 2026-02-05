"""PyInstaller runtime hook to set environment before Qt loads."""

import os
import sys

if sys.platform == "darwin":
    # Disable Qt permission plugins that crash on macOS with PyInstaller
    os.environ["QT_APPLE_DISABLE_PROMPT_ANSWERER"] = "1"
