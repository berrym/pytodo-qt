# pytodo-qt

[![CI](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml/badge.svg)](https://github.com/berrym/pytodo-qt/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A cross-platform to-do list manager with encrypted peer-to-peer synchronization.

## Features

- **Multiple lists** - Organize tasks into separate lists
- **Priority levels** - High, normal, and low priority with color coding
- **Encrypted sync** - AES-256-GCM encryption with Ed25519 key exchange
- **Auto-discovery** - Find other instances on your network via mDNS/Zeroconf
- **Dark/light themes** - System-following or manual theme selection
- **Cross-platform** - Linux, macOS, and Windows support

## Requirements

- Python 3.11 or later
- PyQt6

## Installation

### Pre-built Binaries

Download the latest release for your platform from the [Releases page](https://github.com/berrym/pytodo-qt/releases).

#### macOS

1. Download `pytodo-qt-VERSION-macos-arm64.zip` (Apple Silicon) or `pytodo-qt-VERSION-macos-x86_64.zip` (Intel)
2. Extract the zip file
3. Move `pytodo-qt.app` to `/Applications` or `~/Applications`
4. **First run only:** Right-click the app and select "Open" to bypass Gatekeeper
   - Alternatively, run: `xattr -rd com.apple.quarantine /Applications/pytodo-qt.app`
5. After the first run, you can open normally by double-clicking

> **Note:** The app is ad-hoc signed (not notarized with an Apple Developer ID), so macOS will show an "unidentified developer" warning on first launch. This is normal for open-source software distributed outside the App Store.

#### Linux

1. Download `pytodo-qt-VERSION-linux-x86_64.tar.gz` or `pytodo-qt-VERSION-linux-arm64.tar.gz`
2. Extract: `tar -xzf pytodo-qt-VERSION-linux-*.tar.gz`
3. Run the install script: `cd pytodo-qt-*/ && ./install.sh`
4. Or run directly: `./pytodo-qt`

The install script places the binary in `~/.local/bin/` and creates a desktop entry.

To uninstall: `~/.local/lib/pytodo-qt/uninstall.sh` (or run `./uninstall.sh` from the extracted archive)

#### Windows

1. Download `pytodo-qt-VERSION-windows-x86_64.zip`
2. Extract the zip file
3. Run `pytodo-qt.exe`

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

[appearance]
theme = "system"  # light, dark, system
```

## Synchronization

pytodo-qt uses a secure peer-to-peer protocol for syncing between instances:

1. **Discovery** - Instances advertise themselves via mDNS (`_pytodo._tcp.local.`)
2. **Key exchange** - Ed25519 identity keys with X25519 ephemeral session keys
3. **Encryption** - All data encrypted with AES-256-GCM
4. **Merge** - Last-write-wins conflict resolution with UUID-based items

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

Copyright 2024 Michael Berry <trismegustis@gmail.com>
