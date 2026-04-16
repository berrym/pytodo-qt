# pytodo-qt

[![CI](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml/badge.svg)](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/berrym/pytodo-qt/graph/badge.svg)](https://codecov.io/gh/berrym/pytodo-qt)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![basedpyright](https://img.shields.io/badge/type%20checked-basedpyright-blue.svg)](https://github.com/DetachHead/basedpyright)

A cross-platform to-do list manager with encrypted peer-to-peer synchronization.

## Features

- **Multiple lists** - Organize tasks into separate lists with private/shared control
- **Priority levels** - High, normal, and low priority with color coding
- **Due dates** - Date picker with overdue highlighting and filtering
- **Search and filter** - Real-time filtering of todo items
- **Undo/redo** - Full undo/redo for all operations
- **Encrypted sync** - AES-256-GCM encryption with Ed25519 key exchange
- **Device management** - Track peers by fingerprint with trust levels (normal/trusted/blocked)
- **Sync groups** - Organize devices into groups and control which lists sync where
- **Auto-sync** - Debounced push after changes and periodic full sync on configurable timers
- **Offline queue** - Queue syncs for offline devices, auto-execute when they come online
- **Auto-discovery** - Find other instances on your network via mDNS/Zeroconf
- **Dark/light themes** - WCAG AA contrast-compliant themes with system-following
- **Cross-platform** - Linux, macOS, and Windows support

## Requirements

- Python 3.11 or later
- PyQt6

## Installation

### Pre-built Binaries

Download the latest release for your platform from the [Releases page](https://github.com/berrym/pytodo-qt/releases).

#### macOS

1. Download `pytodo-qt-VERSION-macos-arm64.dmg` (Apple Silicon) or `pytodo-qt-VERSION-macos-x86_64.dmg` (Intel)
2. Open the DMG — a window appears with the app icon and an Applications shortcut
3. Drag `pytodo-qt.app` onto the Applications shortcut
4. Eject the DMG, open `/Applications`, and locate the app
5. **First run only:** right-click the app → **Open** → enter your password → check **Always allow**. macOS asks once because the app uses an ad-hoc signature.
6. After the first launch, open normally by double-clicking

> **Note:** The app is ad-hoc signed (not notarized with an Apple Developer ID), so macOS shows an "unidentified developer" warning on first launch. This is normal for open-source software distributed outside the App Store. The right-click → Open dance is required once per version — subsequent launches of the same version work normally. When upgrading to a new version, drag-replace the existing `/Applications/pytodo-qt.app` with the new one and repeat the right-click → Open flow once.

#### Linux

Two formats are provided for each architecture (`x86_64` and `arm64`).

**AppImage** — single-file, self-contained, no install required:

1. Download `pytodo-qt-VERSION-linux-x86_64.AppImage` (or `-linux-arm64.AppImage`)
2. Make it executable: `chmod +x pytodo-qt-VERSION-linux-x86_64.AppImage`
3. Run it: `./pytodo-qt-VERSION-linux-x86_64.AppImage`

If your distribution dropped `libfuse2` (Ubuntu 22.04+, Fedora 38+), pass `--appimage-extract-and-run` the first time, or install `libfuse2` with your package manager.

**Tarball** — traditional install to `~/.local/`:

1. Download `pytodo-qt-VERSION-linux-x86_64.tar.gz` (or `-linux-arm64.tar.gz`)
2. Extract: `tar -xzf pytodo-qt-VERSION-linux-*.tar.gz`
3. Run the install script: `cd pytodo-qt-*/ && ./install.sh`
4. Or run directly: `./pytodo-qt`

The install script places the binary in `~/.local/bin/` and creates a desktop entry.

To uninstall: `~/.local/lib/pytodo-qt/uninstall.sh` (or run `./uninstall.sh` from the extracted archive)

##### Making the AppImage file show the PyTodo-Qt icon in your file manager

Our AppImage ships with the PyTodo-Qt logo baked in (`.DirIcon`, root PNG, desktop entry at `usr/share/applications/`). Whether the icon actually appears next to the `.AppImage` file in your file manager depends on what your desktop environment has installed — the AppImage ecosystem deliberately keeps this opt-in rather than patching every runtime. Pick whichever of the three fixes below matches your setup:

- **KDE Plasma** (Dolphin, Krusader): install `kio-extras` and `libappimage` — most KDE distributions already ship them. Dolphin will read the embedded `.DirIcon` directly and no further action is needed.

- **GNOME / Cinnamon / XFCE / MATE / elementary** (Nautilus, Nemo, Thunar, Caja, Files): install `xapp-thumbnailers`. It ships by default on Linux Mint and Cinnamon; on Ubuntu, Fedora, Debian, and Arch you will need to install it explicitly (`sudo apt install xapp-thumbnailers`, etc.). Once installed, thumbnails of `.AppImage` files render with the embedded icon.

- **Any desktop, "just works" path**: install [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher). Double-clicking any AppImage the first time will prompt you to integrate it; it then moves the file to `~/Applications/`, extracts the icon, and creates a real desktop entry. From that point on every file manager shows the right icon because the AppImage is a registered application.

None of the above require changes to the AppImage itself — PyTodo-Qt already carries all the metadata these tools look for.

#### Windows

Two formats are provided:

**Installer (recommended)** — installs per-user, creates Start Menu entry, registers for uninstall:

1. Download `pytodo-qt-VERSION-windows-x86_64-setup.exe`
2. Double-click the installer and follow the prompts. No admin rights required — the default install directory is under your user profile, and the installer adds an entry to Windows' "Installed apps" list for clean uninstallation later.
3. Optionally enable the "Create desktop icon" checkbox on the Select Additional Tasks page.

**Zip** — portable, no install required:

1. Download `pytodo-qt-VERSION-windows-x86_64.zip`
2. Extract the zip file to any directory (e.g. your Desktop, a USB drive, or `%LOCALAPPDATA%`)
3. Run `pytodo-qt.exe` from the extracted folder

> **Note:** The installer and the binaries inside the zip are not code-signed. Windows SmartScreen may show a "Windows protected your PC" warning on first launch — click **More info** → **Run anyway**.

#### Checksums

Every artifact ships with a sibling `<filename>.sha256` file in the standard `sha256sum -c` / `shasum -a 256 -c` compatible format. To verify a download:

```bash
# Linux / WSL
sha256sum -c pytodo-qt-VERSION-linux-x86_64.tar.gz.sha256

# macOS
shasum -a 256 -c pytodo-qt-VERSION-macos-x86_64.dmg.sha256

# Windows PowerShell
(Get-FileHash -Algorithm SHA256 pytodo-qt-VERSION-windows-x86_64-setup.exe).Hash.ToLower()
# Then compare against the hash printed in the .sha256 file
```

### From PyPI

```bash
pipx install pytodo-qt    # recommended
pip install pytodo-qt     # alternative
```

### From source

```bash
git clone https://github.com/berrym/pytodo-qt.git
cd pytodo-qt
pip install .
```

### Development install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
pytodo-qt
```

### Command-line options

```
Server Options:
  -s, --server {yes,no}    enable/disable network server
  --pull {yes,no}          allow remote pull requests
  --push {yes,no}          allow remote push requests
  -i, --ip IP              server bind address
  -p, --port PORT          server port

Discovery Options:
  -d, --discovery {yes,no} enable/disable mDNS discovery

Appearance Options:
  -t, --theme {light,dark,system}
```

## Configuration

Configuration is stored in XDG-compliant locations:

| Platform | Config | Data |
|----------|--------|------|
| Linux | `~/.config/pytodo-qt/` | `~/.local/share/pytodo-qt/` |
| macOS | `~/Library/Application Support/pytodo-qt/` | same |
| Windows | `%APPDATA%\pytodo-qt\` | same |

### config.toml

```toml
[database]
active_list = ""
sort_key = "priority"
reverse_sort = false

[server]
enabled = true
address = "0.0.0.0"
port = 5364
allow_pull = true
allow_push = true

[discovery]
enabled = true
service_name = ""  # defaults to pytodo-{hostname}
auto_sync_trusted = false  # auto-sync when trusted devices come online
auto_sync_delay = 0  # seconds to debounce before auto-push (0 = disabled)
auto_sync_interval = 0  # minutes between periodic full syncs (0 = disabled)

[appearance]
theme = "system"  # light, dark, system
```

## Synchronization

pytodo-qt uses a secure peer-to-peer protocol for syncing between instances:

1. **Discovery** - Instances advertise themselves via mDNS (`_pytodo._tcp.local.`)
2. **Key exchange** - Ed25519 identity keys with X25519 ephemeral session keys
3. **Encryption** - All data encrypted with AES-256-GCM
4. **Merge** - Last-write-wins conflict resolution with UUID-based items
5. **Device management** - Track peers with trust levels and organize into sync groups
6. **Sync rules** - Control which lists sync to which device groups
7. **Auto-sync** - Debounced push after changes, periodic full sync, and sync on trusted device discovery
8. **Offline queue** - Queue syncs for offline devices, auto-execute when they come online

Identity keys are stored in your system keyring (GNOME Keyring, macOS Keychain, Windows Credential Locker).

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check
basedpyright src/
```

## License

GPLv3 or later. See [COPYING](COPYING) for details.

Copyright 2024-2026 Michael Berry <trismegustis@gmail.com>
