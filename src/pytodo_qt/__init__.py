"""pytodo-qt - A modern cross-platform to-do application with secure sync.

Version 0.3.0 brings:
- AES-256-GCM authenticated encryption
- Ed25519/X25519 key exchange for secure connections
- UUID-based data model with Lamport timestamps
- Last-Write-Wins sync with conflict tracking
- Zeroconf/mDNS service discovery
- TOML configuration with system keyring integration
- Modern themed UI with light/dark/system mode support

Copyright (C) 2024 Michael Berry
License: GPLv3
"""

from .core.settings import __version__

__all__ = ["__version__"]
