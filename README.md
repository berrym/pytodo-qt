# pytodo-qt

[![CI](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml/badge.svg)](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/berrym/pytodo-qt/graph/badge.svg)](https://codecov.io/gh/berrym/pytodo-qt)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![basedpyright](https://img.shields.io/badge/type%20checked-basedpyright-blue.svg)](https://github.com/DetachHead/basedpyright)

> ## v0.3.11 beta is here
>
> The v0.3.11 beta cycle ships substantial capability beyond v0.3.10. Headline additions:
>
> - **NLP-powered smart task input** with parse-time recognition chips for date, time, tag, priority, recurrence, pomodoro, time block, and inline subtask syntax (`Plan trip: book flight, pack`).
> - **Full calendar surface** — Day, Week, Month, Agenda, and Timeline-Analytics sub-views; Gantt-bar event rendering with eight lifecycle states; drag-and-drop scheduling and edge-drag-to-reschedule.
> - **Web UI** with secure mobile pairing via QR code, per-device authentication tokens, and a mobile-friendly PWA shell.
> - **Kanban board** with drag-and-drop, subtask CRUD, and per-column ordering.
> - **Subtasks** (one-level nesting) with detail-panel CRUD, parent breadcrumb, and inline-syntax creation.
> - **Time blocks and event windows** — `due_time_end` for explicit ranges, named time blocks (`morning`, `late afternoon`, etc.).
> - **Pomodoro and stopwatch** with per-task durations, session logging, and analytics.
> - **Meeting-link Join button** — auto-detection of Zoom, Microsoft Teams, Google Meet, Webex, and Jitsi URLs across the detail panel, kanban card, and calendar context menu.
> - **Tags and private lists**, **WCAG AA themes**, **i18n readiness**, and **filler-word stripping** so natural-speech inputs produce clean reminders.
>
> Download the latest beta from the [Releases page](https://github.com/berrym/pytodo-qt/releases). The most recent prerelease tag (prefix `v0.3.11b`) is the one to try — the page lists releases newest-first, so the top prerelease is the right one.
>
> The beta is suitable for users who want the v0.3.11 capability set or who are willing to help test before the final release. The v0.3.10 stable remains the recommended choice for users requiring strict release-stability guarantees.
>
> **New to installing software from GitHub?** The [Installation](#installation) section below walks through every step, including the file decoder ("which download is for me"), the first-launch warnings each platform shows, and how to verify the download. **Helping test the beta?** See [Helping test the beta](#helping-test-the-beta) for what to try and how to file what you find — being non-technical is welcome.

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

The path most users want is **pre-built binaries**. PyPI and source installs at the bottom of this section are for developers.

### Pre-built Binaries

Download the latest release for your platform from the [Releases page](https://github.com/berrym/pytodo-qt/releases). The page lists releases newest-first; the top entry under the v0.3.11 beta cycle (prefix `v0.3.11b`) is the current beta.

#### Which file do I download?

The Releases page lists several files per release. Pick the one that matches your computer:

| Your system | Download |
|---|---|
| **Mac with Apple Silicon** (M1, M2, M3, M4 — 2020 or later) | `pytodo-qt-VERSION-macos-arm64.dmg` |
| **Mac with Intel processor** (most pre-2020 Macs) | `pytodo-qt-VERSION-macos-x86_64.dmg` |
| **Windows 10 / 11** (most PCs) | `pytodo-qt-VERSION-windows-x86_64-setup.exe` (recommended) or `.zip` (portable) |
| **Linux on most laptops/desktops** (Intel/AMD CPUs) | `pytodo-qt-VERSION-linux-x86_64.AppImage` (recommended) or `.tar.gz` |
| **Linux on Raspberry Pi 4/5 or other ARM hardware** | `pytodo-qt-VERSION-linux-arm64.AppImage` or `.tar.gz` |

**Not sure if your Mac is Apple Silicon or Intel?** Click the Apple menu → About This Mac. If it says "Apple M1/M2/M3/M4" → arm64. If it says "Intel" → x86_64.

**Not sure about your Windows architecture?** Press `Win + Pause/Break` (or Settings → System → About). For nearly all home and office PCs, you want the `x86_64` file.

Each artifact has a sibling `.sha256` file. Verifying the checksum before installing is **optional but recommended for paranoid users** — the [Checksums](#checksums) section below has the per-platform commands.

#### macOS

> **What to expect on first launch:** macOS will refuse to open the app the first time and may show *"Apple could not verify..."* This is **normal** for any open-source app distributed outside the App Store. It happens because pytodo-qt is ad-hoc signed (free) rather than signed with a paid Apple Developer ID ($99/year). The instructions below walk through the one-time approval step. Once approved, the app opens normally on every subsequent launch.

1. Download `pytodo-qt-VERSION-macos-arm64.dmg` (Apple Silicon) or `pytodo-qt-VERSION-macos-x86_64.dmg` (Intel)
2. Open the DMG — a window appears with the app icon and an Applications shortcut
3. Drag `pytodo-qt.app` onto the Applications shortcut
4. Eject the DMG, open `/Applications`, and locate the app
5. **First run only** — pick whichever unblock flow matches your macOS version:

   **macOS Sequoia (15.x) and later** — Apple removed the right-click → Open bypass. Use this flow:
   1. Double-click the app. macOS shows *"pytodo-qt Not Opened — Apple could not verify..."* with only **Done** / **Move to Trash** buttons. Click **Done**.
   2. Open **System Settings → Privacy & Security**.
   3. Scroll to the Security section. You'll see *"pytodo-qt was blocked to protect your Mac"*. Click **Open Anyway**.
   4. Enter your password when prompted, then click **Open** on the re-prompt.

   **macOS Sonoma (14.x) and earlier** — the legacy bypass still works:
   1. Right-click the app → **Open** → click **Open** in the confirmation dialog → enter your password → check **Always allow**.

   **Command-line shortcut (any macOS version)** — strip the quarantine attribute directly:
   ```bash
   xattr -rd com.apple.quarantine /Applications/pytodo-qt.app
   ```
   Then double-click normally.

6. After the first approval, open the app normally by double-clicking.

> **Note:** The app is ad-hoc signed (not notarized with an Apple Developer ID), which is why macOS requires explicit first-launch approval. This is standard for open-source software distributed outside the App Store. When upgrading to a new version, drag-replace the existing `/Applications/pytodo-qt.app` with the new one and re-run whichever approval flow above matches your macOS version.

#### Linux

Two formats are provided for each architecture (`x86_64` and `arm64`).

**AppImage** — single-file, self-contained, no install required:

1. Download `pytodo-qt-VERSION-linux-x86_64.AppImage` (or `-linux-arm64.AppImage`)
2. Make it executable. Either:
   - **In a terminal:** `chmod +x pytodo-qt-VERSION-linux-x86_64.AppImage`
   - **In your file manager:** right-click the file → **Properties** → **Permissions** tab → check **Allow executing file as program** (wording varies by file manager — GNOME Files, Dolphin, Nemo, Thunar all have this option)
3. Run it: double-click in your file manager, or `./pytodo-qt-VERSION-linux-x86_64.AppImage` in a terminal.

If your distribution dropped `libfuse2` (Ubuntu 22.04+, Fedora 38+) you may see a "fuse: not found" error on first launch. Either:
- Run with `--appimage-extract-and-run` once: `./pytodo-qt-VERSION-linux-x86_64.AppImage --appimage-extract-and-run`
- Or install `libfuse2` with your package manager (e.g. `sudo apt install libfuse2`)

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

> **What to expect on first launch:** Windows SmartScreen may show a *"Windows protected your PC"* warning the first time you run the installer or the unzipped `.exe`. This is **normal** for any open-source app that isn't signed with a paid Microsoft / EV code-signing certificate. Click **More info** → **Run anyway** to proceed. Once approved, the app launches normally on every subsequent run.

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

### For developers

These paths assume a working Python 3.11+ environment and are not the recommended route for end users — pre-built binaries above are.

#### From PyPI

```bash
pipx install pytodo-qt    # recommended
pip install pytodo-qt     # alternative
```

#### From source

```bash
git clone https://github.com/berrym/pytodo-qt.git
cd pytodo-qt
pip install .
```

#### Development install

```bash
pip install -e ".[dev]"
```

## Helping test the beta

If you're trying the beta to help test, thank you. Here's a focused list of flows that exercise the most material parts of the app — running through them takes about 15 minutes and surfaces the kinds of issues that benefit most from real-world testing:

1. **Smart input.** In the main window, click the new-item field and type something natural like *"Pick up groceries tomorrow at 5pm #errands p:high"*. Watch for the parse chips to highlight date / time / tag / priority. Hit Enter. The task should appear with the correct fields filled in.
2. **Calendar views.** Switch to the Calendar tab. Try Day, Week, Month, Agenda, and Timeline sub-views. Drag a task from the sidebar onto a day. Drag the bottom edge of a day/week task to extend it.
3. **Detail panel.** Click any task to open its detail panel. Try editing the date, time, priority, recurrence, tags. Add a meeting URL like a Zoom or Teams link — a "Join" button should appear.
4. **Kanban board.** Switch to the Kanban tab. Drag tasks between columns. The state should persist after restart.
5. **Pomodoro / stopwatch.** Open the Focus Timer (clock icon). Start a session against a task. Watch the status bar timer. Stop early and confirm the partial session is logged.
6. **Web UI on a phone or second device on the same network.** Settings → Web → start the server → scan the QR code on a phone browser → confirm the mobile web UI loads and shows your tasks.
7. **Sync between two computers on the same LAN.** Run pytodo-qt on a second machine; both should auto-discover via mDNS. Pair them, push/pull a list, edit on one, watch it land on the other.
8. **Dark/light themes.** Settings → Appearance. Both should look right; let us know if anything reads poorly.

**What to file:** anything that surprised you, looked broken, looked ugly, didn't do what you expected, or made you say "huh." Issues at https://github.com/berrym/pytodo-qt/issues — being non-technical is welcome. The most useful bug report includes:
- What you were doing (one sentence)
- What you expected to happen
- What actually happened
- Your OS (Mac/Windows/Linux + version) and which download you used

Screenshots are gold but optional. Don't worry about whether something is "really" a bug — file it. We'd rather sort through false alarms than miss real issues.

## Need help / something not working?

Trouble installing or first-launch problems:

- **macOS Gatekeeper warning won't go away** — make sure you're following the macOS section above for *your specific macOS version*. Sequoia (15.x) and Sonoma (14.x and earlier) have different bypass flows. The command-line `xattr -rd com.apple.quarantine /Applications/pytodo-qt.app` works on every macOS version if the GUI flows aren't cooperating.
- **Linux AppImage won't run** — see the `libfuse2` note in the AppImage section. If you still hit trouble, the tarball install is a reliable fallback.
- **Windows SmartScreen keeps blocking** — click **More info** → **Run anyway**. If your antivirus is more aggressive, you may need to add an exception for the install location or the unzipped folder.
- **App opens but shows a database error** — the data location is in the [Configuration](#configuration) section below. If you upgraded across a major version, the schema migrates forward automatically. If something looks wrong, file an issue with the log output (run from a terminal to see logs).

If none of the above match what you're seeing, **please open an issue** at https://github.com/berrym/pytodo-qt/issues. Filing an issue is the right thing to do, not a bother — it's how problems get found and fixed. Including your OS, the version of pytodo-qt you tried, and what you saw is enough to start with.

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
