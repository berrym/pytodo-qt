# Security Evolution Guide

This document details the security considerations and implementations needed as pytodo-qt evolves from a LAN sync tool to a full productivity platform.

---

## Current Security Foundation (0.3.x)

The existing implementation provides a solid cryptographic base:

### Cryptographic Primitives

| Component | Algorithm | Purpose |
|-----------|-----------|---------|
| Identity Keys | Ed25519 | Long-term signing/verification |
| Key Exchange | X25519 | Ephemeral key agreement |
| Encryption | AES-256-GCM | Authenticated encryption |
| Key Derivation | HKDF-SHA256 | Session key derivation |
| Password KDF | Argon2id | Password-based keys |

### Security Properties Achieved

- **Forward Secrecy**: New ephemeral keys per session
- **Authentication**: Identity signatures on ephemeral keys
- **Confidentiality**: AES-256-GCM encryption
- **Integrity**: GCM authentication tags
- **MITM Prevention**: Signed key bundles bind ephemeral to identity

### Current Trust Model

Trust-On-First-Use (TOFU): When first connecting to a peer, the identity fingerprint is displayed. Users implicitly trust peers they connect to.

---

## Phase 1 Security: Server Mode & Multi-User

### New Attack Surface

Moving to server mode introduces:

- WAN exposure (internet-facing service)
- User authentication (password attacks)
- Session management (token theft)
- Multi-user data isolation

### Required Implementations

#### TLS Transport Security

```
Client ──── TLS 1.3 ──── Server
```

**Implementation:**
- Let's Encrypt integration for automatic certificates
- ACME protocol support for certificate renewal
- Fallback to self-signed for LAN-only deployments
- TLS 1.3 only (no legacy protocol support)
- Strong cipher suite configuration

**Configuration Example:**
```toml
[server.tls]
enabled = true
cert_path = "/etc/pytodo-qt/cert.pem"
key_path = "/etc/pytodo-qt/key.pem"
acme_email = "admin@example.com"  # For Let's Encrypt
```

#### User Authentication

**Password Storage:**
- Argon2id with recommended parameters (already implemented)
- Minimum password length: 12 characters
- Password strength meter in UI
- No password hints or security questions

**Session Management:**
- Cryptographically random session tokens (256-bit)
- Secure token storage (keyring on desktop, secure storage on mobile)
- Session expiration (configurable, default 30 days)
- Session revocation capability

**Authentication Flow:**
```
1. Client sends username + password over TLS
2. Server verifies against Argon2id hash
3. Server generates session token
4. Client stores token securely
5. Subsequent requests use token (not password)
```

#### Brute Force Protection

**Rate Limiting:**
- 5 failed attempts: 1 minute lockout
- 10 failed attempts: 15 minute lockout
- 20 failed attempts: 1 hour lockout + admin notification

**Implementation:**
- Per-IP rate limiting
- Per-account rate limiting (independent)
- Fail2ban integration for severe cases

#### Multi-User Data Isolation

**Database Design:**
- All records tagged with user_id
- Queries always filtered by authenticated user
- No direct record ID access (use user-scoped lookups)

**API Design:**
- No endpoint returns data without user context
- Shared lists have explicit permission checks
- Admin operations require separate privilege level

### Security Checklist: Phase 1

- [ ] TLS implementation with auto-renewal
- [ ] Session token generation and validation
- [ ] Rate limiting middleware
- [ ] User-scoped database queries
- [ ] Password strength requirements
- [ ] Secure session storage (client-side)
- [ ] Failed login monitoring
- [ ] Security headers (HSTS, etc.)

---

## Phase 2 Security: Web Interface & API

### New Attack Surface

Web interfaces introduce:

- Cross-Site Scripting (XSS)
- Cross-Site Request Forgery (CSRF)
- API authentication and authorization
- Browser-based credential storage

### Required Implementations

#### Web Application Security

**Content Security Policy:**
```http
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data:;
  connect-src 'self' wss:;
  frame-ancestors 'none';
```

**Additional Headers:**
```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

**CSRF Protection:**
- Double-submit cookie pattern
- SameSite=Strict cookies
- Origin header validation

#### API Security

**Authentication Options:**
1. **Session Cookies** (web UI)
   - HttpOnly, Secure, SameSite=Strict
   - CSRF token required for mutations

2. **Bearer Tokens** (API clients)
   - JWT or opaque tokens
   - Short expiration (1 hour) with refresh tokens
   - Revocation via token blacklist

3. **API Keys** (integrations)
   - Long-lived, scoped tokens
   - Rate limited separately
   - Revocable per-key

**Authorization Model:**
```
User
 ├── Owns lists (full control)
 ├── Edits shared lists (modify items)
 └── Views shared lists (read only)
```

#### WebSocket Security

**Connection:**
- Require valid session before WebSocket upgrade
- Validate Origin header
- Rate limit message frequency

**Messages:**
- Authenticate every message (include session token)
- Validate message schema
- Sanitize before broadcast to other sessions

### Security Checklist: Phase 2

- [ ] Content Security Policy implementation
- [ ] CSRF protection for all mutations
- [ ] Secure cookie configuration
- [ ] API authentication (tokens, API keys)
- [ ] WebSocket authentication
- [ ] Input validation and sanitization
- [ ] Output encoding (XSS prevention)
- [ ] CORS configuration
- [ ] Rate limiting per endpoint

---

## Phase 3 Security: Mobile Apps & Relay

### New Attack Surface

Mobile and relay introduce:

- Mobile credential storage
- Push notification security
- Relay server trust model
- Cross-platform key synchronization

### Required Implementations

#### Mobile Security

**Credential Storage:**

| Platform | Storage |
|----------|---------|
| Android | EncryptedSharedPreferences + Keystore |
| iOS | Keychain Services |

**Biometric Authentication:**
- Optional biometric unlock for app
- Keys never leave secure enclave
- Fallback to PIN/password

**App Security:**
- Certificate pinning for server connections
- No sensitive data in logs
- Secure data directory permissions
- Obfuscation for release builds

#### Push Notification Security

**Problem:** Push providers (FCM, APNs) can see notification content.

**Solution:** Encrypted push payloads
```
1. Server sends: { "type": "sync", "data": <encrypted> }
2. Notification displays generic message
3. App decrypts payload to get actual content
4. Optionally update notification with decrypted preview
```

**Alternative:** Data-only pushes (wake app, fetch via encrypted channel)

#### Zero-Knowledge Relay

If the optional relay service is implemented:

**Architecture:**
```
Client A                    Relay                    Client B
   │                          │                          │
   │── Encrypted Blob ───────►│                          │
   │                          │── Encrypted Blob ───────►│
   │                          │                          │
   │   (Relay cannot read)    │                          │
```

**Guarantees:**
- Relay stores only AES-256-GCM encrypted blobs
- Encryption keys never touch relay
- Metadata minimization (padding, timing obfuscation)
- No logging of user associations

**Verification:**
- Open source relay implementation
- Independent security audit
- Reproducible builds

### Security Checklist: Phase 3

- [ ] Mobile secure storage implementation
- [ ] Biometric authentication
- [ ] Certificate pinning
- [ ] Encrypted push notifications
- [ ] Relay zero-knowledge architecture
- [ ] Security audit (external)
- [ ] Penetration testing
- [ ] Bug bounty program consideration

---

## Threat Model

### Threat Actors

| Actor | Capability | Goal |
|-------|------------|------|
| Script Kiddie | Automated tools | Opportunistic access |
| Motivated Individual | Targeted attacks | Specific user data |
| Criminal Organization | Sophisticated tools | Mass data theft |
| Nation State | Advanced persistent | Targeted surveillance |

### Defense Priorities

**High Priority (All Phases):**
- Encryption in transit (TLS)
- Encryption at rest (AES-256-GCM)
- Authentication (strong passwords, sessions)
- Input validation (prevent injection)

**Medium Priority (Phase 2+):**
- Rate limiting
- Audit logging
- Intrusion detection

**Lower Priority (Phase 3+):**
- Advanced threat detection
- Formal verification
- Bug bounty program

### What We Don't Protect Against

Being explicit about limitations:

- **Compromised Device**: If the user's device is compromised, the attacker has access to decrypted data
- **Rubber Hose Cryptanalysis**: If a user is coerced to reveal passwords
- **Implementation Bugs**: Despite best efforts, bugs may exist
- **Side Channels**: Timing attacks, power analysis (not applicable for most users)

---

## Security Testing Strategy

### Automated Testing

**Unit Tests:**
- Cryptographic operations produce expected output
- Authentication rejects invalid credentials
- Authorization blocks unauthorized access

**Integration Tests:**
- Full handshake completes successfully
- Session management lifecycle
- Rate limiting triggers correctly

**Static Analysis:**
- Bandit (Python security linter)
- Dependency vulnerability scanning (safety, pip-audit)
- Secret detection in code

### Manual Testing

**Pre-Release Checklist:**
- [ ] Attempt SQL/command injection on all inputs
- [ ] Test authentication bypass scenarios
- [ ] Verify TLS configuration (SSL Labs)
- [ ] Check for information leakage in errors
- [ ] Test session invalidation
- [ ] Verify rate limiting effectiveness

**Periodic Review:**
- Quarterly dependency audit
- Annual threat model review
- Security-focused code review for sensitive changes

### External Assessment

**Before 1.0 Release:**
- Professional penetration test
- Cryptographic implementation review
- Consider bug bounty program

---

## Incident Response

### Preparation

- Maintain security contact email
- Document escalation procedures
- Prepare disclosure templates

### Response Process

1. **Identification**: Confirm vulnerability is real
2. **Containment**: Limit exposure if actively exploited
3. **Eradication**: Develop and test fix
4. **Recovery**: Deploy fix, verify resolution
5. **Lessons Learned**: Update processes to prevent recurrence

### Disclosure Policy

- Security issues reported privately get 90 days before public disclosure
- Credit researchers who report responsibly
- Publish post-mortems for significant issues

---

## Cryptographic Agility

### Future-Proofing

The protocol version field allows cryptographic algorithm upgrades:

```
Protocol v2: Ed25519 + X25519 + AES-256-GCM
Protocol v3: (future) Post-quantum algorithms when standardized
```

### Migration Strategy

1. Add support for new algorithms in new protocol version
2. Clients negotiate highest mutually supported version
3. Deprecate old versions after transition period
4. Eventually remove legacy support

### Post-Quantum Consideration

Current algorithms (Ed25519, X25519) are vulnerable to quantum computers. When NIST post-quantum standards mature:

- **Key Exchange**: ML-KEM (CRYSTALS-Kyber)
- **Signatures**: ML-DSA (CRYSTALS-Dilithium)

Timeline: Not urgent for task management app. Monitor NIST standardization.

---

## Summary

Security evolves with the product:

| Phase | Focus | Key Additions |
|-------|-------|---------------|
| Current | LAN security | E2E encryption, forward secrecy |
| Phase 1 | WAN security | TLS, authentication, rate limiting |
| Phase 2 | Web security | CSRF, CSP, API auth |
| Phase 3 | Mobile/Relay | Secure storage, zero-knowledge |

The foundation is solid. Each phase builds incrementally on what exists, maintaining security as a core feature rather than an afterthought.
