# dmgbuild settings file for the macOS .dmg artifact.
#
# Variables passed via dmgbuild's `-D key=value` flag are exposed as
# locals in this module. Required defines:
#   - app_path: filesystem path to the built pytodo-qt.app bundle
#   - background_path: path to the DMG window background PNG

import os

# Resolve injected defines
_defines = locals()
_app_path = _defines.get("app_path", "dist/pytodo-qt.app")
_background_path = _defines.get("background_path", "packaging/macos/dmg_background.png")
_app_name = os.path.basename(_app_path)


# --- Disk image format -----------------------------------------------------

format = "UDZO"
filesystem = "HFS+"

# Size left as None so dmgbuild auto-sizes around the contents.
size = None


# --- Files / symlinks ------------------------------------------------------

files = [_app_path]
symlinks = {"Applications": "/Applications"}


# --- Hide list -------------------------------------------------------------
#
# `hide` instructs dmgbuild to omit these entries from the icon view's
# visible item list when writing the .DS_Store. Combined with
# `icon_locations` placing them far offscreen, the entries do not appear
# in Finder regardless of the user's hidden-files preference (Cmd+Shift+.
# does not surface items not present in the icon view's saved item list).
#
# dmgbuild copies the configured background image into the DMG root as
# `.background.<ext>` where <ext> matches the source file's extension
# (so `dmg_background.png` becomes `.background.png` at the root). Both
# the legacy `.background/` directory name and the actual `.background.png`
# file name are listed for safety across dmgbuild internal changes.

hide = [
    ".background",
    ".background.png",
    ".background.jpg",
    ".background.tiff",
    ".DS_Store",
    ".fseventsd",
    ".Trashes",
    ".VolumeIcon.icns",
]


# --- Icon positions --------------------------------------------------------
#
# Visible items get explicit in-window coordinates. Hidden system items
# get positions far outside the window so even users who toggle hidden
# files visible cannot see them in the default window bounds.

icon_locations = {
    _app_name: (150, 180),
    "Applications": (450, 180),
    ".background": (10000, 10000),
    ".background.png": (10000, 10000),
    ".background.jpg": (10000, 10000),
    ".background.tiff": (10000, 10000),
    ".DS_Store": (10000, 10000),
    ".fseventsd": (10000, 10000),
    ".Trashes": (10000, 10000),
    ".VolumeIcon.icns": (10000, 10000),
}


# --- Window -----------------------------------------------------------------

window_rect = ((200, 120), (600, 400))
default_view = "icon-view"
show_icon_preview = False
include_icon_view_settings = "auto"
include_list_view_settings = "auto"


# --- Icon view --------------------------------------------------------------

icon_size = 100
text_size = 16
grid_offset = (0, 0)
grid_spacing = 100.0
scroll_position = (0, 0)
label_pos = "bottom"
arrange_by = None


# --- Background -------------------------------------------------------------

background = _background_path
