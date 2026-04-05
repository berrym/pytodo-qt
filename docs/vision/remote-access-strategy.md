# Remote Access Strategy

**Status:** Active design document
**Last reviewed:** 2026-04-05

This document explains pytodo-qt's current LAN-first design, why it fails in cross-network scenarios, and the realistic path forward for users who need remote access today and in the future.

---

## Current Design: LAN-First by Intent

pytodo-qt is a LAN-first, P2P-synced todo application. Mobile access via the embedded web server works when phone and desktop share the same network. This is not an accidental limitation — it is the deliberate consequence of several explicit design choices:

- **No cloud dependency** — no servers to trust, no accounts to manage, no subscription
- **mDNS-based discovery** — `.local` hostname resolution for IP-change resilience on home networks
- **Self-signed TLS with a local CA** — no public certificate authority involvement
- **End-to-end encrypted P2P sync** — peers authenticate each other directly

These choices maximize user sovereignty and minimize trust surface. They also mean remote access (phone on cellular, laptop on hotel/hospital/corporate wifi) does not work out of the box. That trade-off is intentional.

## Why Remote Access Fails

A common user journey: take the laptop to a public location, try to open the mobile access wizard from a phone on cellular data or a different network, and it doesn't work. Here is exactly why:

### Barrier 1: Client Isolation
Most public wifi networks (hotels, airports, hospitals, cafes) enable **client isolation** — devices on the same SSID cannot communicate with each other. Your phone and laptop may both be "on the network" but cannot reach each other directly.

### Barrier 2: NAT and Private IP Ranges
The IP address assigned to your laptop on any wifi network is private (`10.x.x.x`, `172.16-31.x.x`, or `192.168.x.x`). These addresses are not routable from outside that network. A phone on cellular or a different network cannot reach them, even if it knows the IP.

### Barrier 3: mDNS Boundary
`.local` hostname resolution uses multicast DNS, which does not cross subnet boundaries. Even on the same physical network, if the phone and laptop are on different subnets (common in corporate/guest wifi splits), `.local` lookup silently fails.

### Barrier 4: Certificate Mismatch
Even if the other three barriers were overcome, the self-signed TLS certificate's Subject Alternative Name includes the mDNS hostname and the discovered LAN IPs — not arbitrary public addresses. A connection attempt would trigger a certificate warning that most mobile browsers will not let users bypass.

**All four barriers typically hit simultaneously on public wifi.** There is no simple "enter the IP instead" fix, because the IP itself isn't reachable.

## What Works Today

### On the Same LAN
The wizard and QR-code pairing work well on home wifi, trusted office networks, and cellular tethering (phone tethers to laptop, creating a shared micro-network).

### Via User-Installed Tunnel
Users who want remote access today can run a mesh VPN or tunnel service that creates a logical network spanning their devices:

**Recommended: [Tailscale](https://tailscale.com/)**
- Free tier covers personal use (100 devices, 3 users)
- Installs on desktop and phone
- Creates a WireGuard-based mesh network with stable hostnames
- Use the Tailscale hostname in place of `.local` in the mobile access wizard
- Zero code changes in pytodo-qt

**Alternative: [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/)**
- Free tier available
- Gives your laptop's web server a public HTTPS URL
- Runs outbound-only (punches through any firewall)
- User controls authentication via Cloudflare Access

**Alternative: Self-hosted WireGuard**
- For users who want no third-party involvement
- Requires a VPS or home server with a public IP
- More setup effort, zero trust surface beyond your own infrastructure

These are all user-installed solutions. pytodo-qt treats them as transparent — from the app's perspective, a Tailscale hostname is just another hostname.

### Via Cellular Tethering
The simplest workaround for occasional remote use: tether the phone to the laptop. Both devices land on the same micro-LAN, mDNS works, and the wizard QR code works unmodified.

## What's Coming

### 0.4.x Series: Headless Server Mode (Planned)

The 0.4.x series will introduce a headless server mode — a pytodo-qt server that runs on a VPS, home server, or NAS, reachable via a public hostname and TLS certificate from a public CA.

In this model:
- The server is always reachable (it has a public address)
- Phone connects to the server from anywhere
- Desktop syncs to the server via existing P2P mechanisms when on LAN
- The "both endpoints must be reachable" problem disappears

This is the proper answer to the cross-network problem. It does not require pytodo-qt to host infrastructure — users self-host on hardware they control. It does not compromise the local-first architecture — the desktop app continues to work fully offline.

### Post-0.4.x: Optional Managed Relay (Under Consideration)

For users who don't want to self-host a server, an **optional** zero-knowledge relay is on the longer-term roadmap. Key properties:

- **Zero-knowledge**: relay stores only AES-256-GCM encrypted blobs; keys never leave client devices
- **Opt-in**: disabled by default, with a clear "kill switch" setting that blocks all cloud traffic
- **Self-hostable**: the relay is open source and can be self-hosted, not only run by the project
- **No lock-in**: users can migrate data to a self-hosted server at any time

This represents a possible evolution — not a decision already made. The 0.4.x server mode may prove sufficient for real needs.

## Scope Boundary: pytodo-qt vs. Future Brand

pytodo-qt itself will remain LAN-first, P2P, self-hosted. It will not grow a cloud service, managed relay, or built-in remote access beyond documenting Tailscale-style user-installed tunnels.

The 0.4.x series (with headless server mode, PySide6 migration, and potential license change) will likely ship under a **new project identity**. This preserves pytodo-qt as a stable, predictable option for users who want exactly what it is today — while letting the cloud/collaborative/cross-network direction evolve without disturbing that contract.

Users who chose pytodo-qt for its LAN-only, local-first posture will not have the ground shift under them. Users who need remote access will have a clear next step when it arrives.

## Summary Table

| Scenario | Today | 0.4.x | Post-0.4.x |
|---|---|---|---|
| Same LAN (home wifi) | Wizard + QR code | Same, plus server mode | Same |
| Cellular tethering | Works | Works | Works |
| Different networks, user runs Tailscale | Works (documented) | Works | Works |
| Different networks, no VPN | **Not supported** | Server mode | Server mode or opt-in relay |
| User wants zero cloud touch | Self-host only | Self-host server | Self-host + kill switch |

## For Users Hitting the Wall

If you are trying to use pytodo-qt mobile access from outside your home network and it isn't working, here is the current prescribed path:

1. **Confirm you are on the same wifi network** as the desktop (not a separate "guest" SSID)
2. **If the `.local` hostname fails**, try the LAN IP directly — most corporate/guest networks block mDNS but allow direct IP
3. **If you are on a different network**, install Tailscale on both devices — this is today's supported remote-access path
4. **If tethering is available**, tether the phone to the laptop as a quick workaround

Cross-network access without a VPN is a known limitation we are actively planning to solve — not in pytodo-qt, but in the 0.4.x server mode that will ship under a new project identity.
