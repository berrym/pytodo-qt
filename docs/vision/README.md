# pytodo-qt Vision

This directory contains the strategic vision and future direction documentation for pytodo-qt.

## Overview

pytodo-qt began as a desktop todo list application with secure LAN synchronization - a solid, privacy-respecting tool for personal task management. The project has reached a mature state with:

- Clean PyQt6 desktop interface
- Robust cryptographic foundation (Ed25519/X25519/AES-256-GCM)
- mDNS/Zeroconf peer discovery
- CRDT-style sync with conflict resolution
- Cross-platform support (Linux, macOS, Windows)

While pytodo-qt excels at what it was designed to be, the landscape of personal productivity software has evolved. There is a growing demand for privacy-respecting, user-controlled alternatives to cloud-dependent services. pytodo-qt is well-positioned to evolve into something more significant while maintaining its core values.

## Documents

### [Strategic Roadmap](./strategic-roadmap.md)

**The guiding vision for pytodo-qt's future development.**

This document outlines the primary direction for the project: evolving from a personal LAN sync tool into a privacy-first, self-hostable collaborative task management platform. This roadmap represents the strategic north star for development decisions.

### [Explored Directions](./explored-directions.md)

A comprehensive analysis of potential future directions that were considered during strategic planning. These alternatives informed the strategic roadmap and may provide inspiration for future features or pivot points.

### [Security Evolution](./security-evolution.md)

Detailed security considerations and implementation guidance for each development phase. Covers threat modeling, specific security implementations needed, and testing strategies.

## Core Principles

As pytodo-qt evolves, these principles guide development decisions:

1. **Privacy by Design** - Users own their data. No telemetry, no cloud dependency by default.

2. **Local-First** - The app works fully offline. Sync is additive, not required.

3. **Security Without Complexity** - Strong cryptography should be invisible to users.

4. **Self-Hosting Friendly** - Running your own server should be straightforward.

5. **Open and Transparent** - Open source, auditable, no vendor lock-in.

## Version Generations

| Generation | Focus | Status |
|------------|-------|--------|
| 0.1.x - 0.3.x | Desktop app, LAN sync | Current |
| 0.4.x | Server mode, multi-user foundation | Planned |
| 0.5.x | Web interface, mobile foundations | Future |
| 1.0.x | Full platform with mobile apps | Vision |

## Contributing to the Vision

The strategic roadmap is a living document. As development progresses and the landscape evolves, the vision may be refined. Major directional changes should be discussed and documented here before implementation.
