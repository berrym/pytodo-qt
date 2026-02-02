# Strategic Roadmap

> **This document defines the guiding vision for pytodo-qt's future development.**

## Executive Summary

pytodo-qt will evolve from a personal desktop LAN sync application into a **privacy-first, self-hostable collaborative task management platform**. The core proposition:

**"Todoist for people who care about privacy"**

Users will be able to:
- Run their own pytodo server on personal hardware or a VPS
- Access tasks from desktop, web, and mobile clients
- Collaborate with family, friends, or small teams
- Optionally use a managed relay service while maintaining end-to-end encryption

This positions pytodo-qt in a real, underserved market segment: users who want modern productivity tools without surrendering their data to cloud providers.

---

## The Vision

### What pytodo-qt Becomes

A complete task management ecosystem where:

1. **You own your data** - Tasks live on your hardware, not someone else's servers
2. **Sync just works** - Seamless synchronization across all your devices
3. **Collaboration is private** - Share lists with others without a middleman reading them
4. **Self-hosting is simple** - Deploy on a Raspberry Pi, NAS, or cheap VPS in minutes

### Target Users

- Privacy-conscious individuals
- Families wanting shared task lists
- Small teams and businesses with data sovereignty requirements
- Developers and technical users who appreciate self-hosting
- Anyone uncomfortable with their todo list being mined for advertising data

### Market Positioning

| Feature | Cloud Services (Todoist, etc.) | pytodo-qt |
|---------|-------------------------------|-----------|
| Data Location | Their servers | Your hardware |
| Encryption | At rest (they hold keys) | End-to-end (you hold keys) |
| Offline Support | Limited | Full |
| Self-Hosting | No | Yes |
| Subscription | Required | Optional relay only |
| Open Source | No | Yes |

---

## Development Phases

### Phase 1: Server Mode & Multi-User Foundation

**Target: 0.4.x release series**

Transform pytodo-qt from a peer-to-peer sync tool into a proper client-server architecture.

#### Goals

1. **Dedicated Server Mode**
   - Run pytodo-qt as a headless service
   - Persistent storage and always-on sync endpoint
   - Configuration via file and environment variables
   - Systemd service file for Linux deployment

2. **User Account System**
   - Local user accounts with secure password storage (Argon2id)
   - Session management with token-based authentication
   - Basic user administration

3. **Multi-User Data Model**
   - User-scoped task lists
   - Foundation for sharing (list ownership, permissions)
   - Database schema evolution for multi-tenancy

4. **Improved Desktop Client**
   - Connect to remote server (not just LAN peers)
   - Account login/logout
   - Server configuration UI

#### Security Additions

- TLS support for WAN connections
- Session tokens with secure storage
- Rate limiting for authentication endpoints
- Password strength requirements

#### Deliverables

- `pytodo-qt server` command for headless operation
- User registration and authentication
- Docker image for easy deployment
- Updated documentation for server setup

---

### Phase 2: Web Interface & Mobile Foundation

**Target: 0.5.x release series**

Expand access beyond the desktop with a web interface and lay groundwork for mobile.

#### Goals

1. **Web Interface**
   - Browser-based task management
   - Responsive design (works on tablets/phones in browser)
   - Same feature set as desktop for core operations
   - Progressive Web App (PWA) capabilities

2. **REST/WebSocket API**
   - Documented API for third-party integrations
   - WebSocket for real-time updates
   - API authentication (tokens, API keys)

3. **Mobile App Foundation**
   - Evaluate framework (Flutter, React Native, or native)
   - Core sync library that can be shared
   - Push notification infrastructure design

4. **Enhanced Collaboration**
   - List sharing between users
   - Permission levels (owner, editor, viewer)
   - Sharing invitations

#### Technical Decisions

- **Web Framework**: Consider FastAPI or Quart for async Python backend
- **Frontend**: Vue.js, React, or Svelte for the web UI
- **Mobile**: Flutter recommended for cross-platform with single codebase

#### Security Additions

- CORS configuration for web clients
- CSRF protection
- Content Security Policy headers
- API rate limiting

#### Deliverables

- Functional web interface
- Public API documentation
- Mobile app architecture document
- Sharing and collaboration features

---

### Phase 3: Mobile Apps & Platform Maturity

**Target: 0.6.x - 1.0.x release series**

Complete the platform with native mobile experiences and production-ready reliability.

#### Goals

1. **Native Mobile Apps**
   - Android app (Google Play)
   - iOS app (App Store)
   - Offline-first with background sync
   - Push notifications for shared list updates

2. **Optional Managed Relay**
   - Cloud relay service for users who don't want to self-host
   - Zero-knowledge architecture (server sees only encrypted blobs)
   - Simple pricing (storage-based, no per-user fees)
   - Bridge for NAT traversal

3. **Production Hardening**
   - Comprehensive logging and monitoring hooks
   - Backup and restore tools
   - Migration utilities for version upgrades
   - Performance optimization for larger deployments

4. **Platform Features**
   - Due dates with reminders
   - Recurring tasks
   - Tags and filters
   - Search across all lists
   - Import from other services (Todoist, Things, etc.)

#### Security Additions

- Mobile credential secure storage (Keychain/Keystore)
- Push notification privacy (encrypted payloads)
- Security audit for 1.0 release
- Bug bounty program consideration

#### Deliverables

- Published mobile apps
- Optional relay service (if pursued)
- 1.0 stable release
- Comprehensive user documentation

---

## Technical Architecture Evolution

### Current Architecture (0.3.x)

```
┌─────────────┐         ┌─────────────┐
│  Desktop    │◄──LAN──►│  Desktop    │
│  Client     │  Sync   │  Client     │
└─────────────┘         └─────────────┘
     │                        │
     └────── mDNS Discovery ──┘
```

### Phase 1 Architecture (0.4.x)

```
┌─────────────┐         ┌─────────────┐
│  Desktop    │         │  Desktop    │
│  Client     │         │  Client     │
└──────┬──────┘         └──────┬──────┘
       │                       │
       └───────┬───────────────┘
               │
        ┌──────▼──────┐
        │   Server    │
        │  (self-    │
        │   hosted)   │
        └─────────────┘
```

### Phase 2-3 Architecture (0.5.x+)

```
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ Desktop │ │   Web   │ │ Android │ │   iOS   │
│ Client  │ │ Client  │ │   App   │ │   App   │
└────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘
     │           │           │           │
     └───────────┴─────┬─────┴───────────┘
                       │
                ┌──────▼──────┐
                │   Server    │
                │ (self-host  │
                │  or relay)  │
                └─────────────┘
```

---

## Security Evolution

The existing cryptographic foundation (Ed25519, X25519, AES-256-GCM) scales to the full vision. Key additions by phase:

### Phase 1 Security

| Component | Implementation |
|-----------|----------------|
| TLS | Let's Encrypt integration, auto-renewal |
| Authentication | Argon2id password hashing, secure sessions |
| Authorization | User-scoped data access |
| Rate Limiting | Fail2ban-style protection |

### Phase 2 Security

| Component | Implementation |
|-----------|----------------|
| API Security | OAuth2/JWT tokens, API key management |
| Web Security | CSRF, CSP, secure cookies |
| Sharing | Cryptographic access control for shared lists |

### Phase 3 Security

| Component | Implementation |
|-----------|----------------|
| Mobile Security | Secure enclaves, biometric unlock |
| Relay Zero-Knowledge | Server never sees plaintext |
| Audit | Formal security review before 1.0 |

---

## Success Metrics

### Phase 1
- Server can run continuously for 30+ days without intervention
- 10+ concurrent users on single instance
- Sub-second sync latency on LAN

### Phase 2
- Web interface feature parity with desktop
- API response time < 100ms for common operations
- Documentation sufficient for third-party integrations

### Phase 3
- Mobile apps rated 4+ stars
- Self-hosting guide completable in < 30 minutes
- Zero critical security vulnerabilities at 1.0

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Scope creep | Delayed releases | Strict phase boundaries, MVP mindset |
| Mobile development complexity | Resource drain | Consider Flutter for single codebase |
| Security vulnerabilities | Reputation damage | Security-first design, external audit |
| Low adoption | Wasted effort | Validate with community before major features |
| Maintenance burden | Burnout | Keep architecture simple, automate testing |

---

## Open Questions

These decisions can be deferred but should be resolved before their respective phases:

### Phase 1
- Database: Continue with JSON file or migrate to SQLite?
- Configuration: TOML, YAML, or environment variables only?

### Phase 2
- Web framework: FastAPI, Quart, or something else?
- Frontend framework: Vue, React, Svelte?
- Mobile framework: Flutter, React Native, or native?

### Phase 3
- Relay service: Self-operated or partner with privacy-focused hosting?
- Pricing model: Free tier + paid storage? One-time purchase?

---

## Conclusion

This roadmap transforms pytodo-qt from a well-crafted personal tool into a privacy-respecting productivity platform. The journey is ambitious but achievable:

- **Phase 1** builds the foundation with server mode and multi-user support
- **Phase 2** expands reach with web and mobile groundwork
- **Phase 3** completes the vision with native apps and production polish

The core value proposition remains constant throughout: **your tasks, your data, your control**.

Development will proceed thoughtfully, with each phase validated before moving to the next. The existing codebase provides a solid foundation - the cryptographic layer, sync engine, and data model were designed with extensibility in mind.

The future of pytodo-qt is a future where privacy and productivity coexist.
