# PWA & Mobile Strategy — Design Document

## Purpose

This document describes Phase 6 of the v0.3.11 release: Progressive Web App (PWA) enhancements that transform the Web UI from a network-dependent web page into an installable, offline-capable mobile experience. It also places this work in context of the project's broader mobile access strategy.

## Where This Fits

The mobile access journey has three stages:

```
Stage 1: Web UI (Phase 5)          Stage 2: PWA (Phase 6)         Stage 3: Server Mode (v0.4.x)
┌────────────────────────┐         ┌────────────────────────┐     ┌────────────────────────┐
│ Embedded web server    │         │ Installable on phone   │     │ Headless server mode   │
│ Mobile-optimized HTML  │         │ Offline viewing        │     │ Runs without desktop   │
│ Same-network only      │───────→│ Offline editing        │────→│ Accessible from        │
│ Desktop must be running│         │ Sync on reconnect      │     │   anywhere (Tailscale, │
│ No offline support     │         │ Still needs same       │     │   port forward, relay) │
│                        │         │   network & desktop    │     │ Always available        │
└────────────────────────┘         └────────────────────────┘     └────────────────────────┘
```

Stage 1 (Phase 5) provides the baseline: a working web interface on the local network. Stage 2 (Phase 6, this document) adds resilience — the web app works even when the network connection drops temporarily. Stage 3 (v0.4.x, future release) removes the dependency on the desktop app entirely.

## What PWA Adds

A Progressive Web App is a web page that opts into native-app-like capabilities through three standard browser APIs:

### 1. Web App Manifest

A JSON file (`manifest.json`) that tells the browser how to install the web app:

```json
{
  "name": "PyTodo-Qt",
  "short_name": "PyTodo",
  "description": "Privacy-first todo manager",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#2196F3",
  "icons": [
    {
      "src": "/static/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/static/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

**What this enables:**
- "Add to Home Screen" prompt on Android Chrome and iOS Safari
- App appears in the phone's app drawer with its own icon
- Launches in standalone mode (no browser chrome — looks like a native app)
- Theme-colored status bar on Android

### 2. Service Worker

A JavaScript file (`sw.js`) that acts as a programmable network proxy between the web app and the server. It intercepts every HTTP request and can serve cached responses when the network is unavailable.

### 3. Offline Storage

`localStorage` and `IndexedDB` provide client-side persistence for offline edits that need to be synced back when the network returns.

## Service Worker Design

### Caching Strategy

The service worker uses two different strategies depending on what's being requested:

```
Request                              Strategy              Why
──────────────────────────────────  ────────────────────  ─────────────────────────
/static/index.html                  Cache-first           Static asset, rarely changes
/static/style.css                   Cache-first           Static asset
/static/app.js                      Cache-first           Static asset
/static/icon-*.png                  Cache-first           Static asset
/api/lists                          Network-first         Want fresh data if possible
/api/lists/{id}                     Network-first         Want fresh data if possible
/api/items/{id}/toggle              Network-only + queue  Write operation
POST /api/lists/{id}/items          Network-only + queue  Write operation
PUT /api/items/{id}                 Network-only + queue  Write operation
DELETE /api/items/{id}              Network-only + queue  Write operation
```

### Cache-First (Static Assets)

```
Browser ──→ Service Worker ──→ Cache hit? ──→ Return cached response
                                    │
                                    └── Cache miss ──→ Fetch from network
                                                            │
                                                            └── Cache response, return it
```

Static assets change only when a new version of the app is deployed. The service worker caches them on first load and serves from cache thereafter. Cache invalidation happens when the service worker version changes (a version string in `sw.js` triggers a cache refresh).

### Network-First (API Reads)

```
Browser ──→ Service Worker ──→ Try network ──→ Success? ──→ Cache response, return it
                                    │
                                    └── Network error ──→ Return cached response
                                                              │
                                                              └── No cache? ──→ Offline page
```

API reads try the network first (we want fresh data). If the network fails (phone moved to a room without WiFi, desktop closed, etc.), the service worker falls back to the last cached response. This gives users read access to their most recent todo state even when offline.

### Network-Only + Queue (API Writes)

```
Browser ──→ Service Worker ──→ Try network ──→ Success? ──→ Return response
                                    │
                                    └── Network error ──→ Queue in localStorage
                                                              │
                                                              └── Return "queued" response
```

Write operations cannot be served from cache — they must reach the server. When offline, writes are queued in `localStorage` for replay when the network returns.

### Cache Versioning

```javascript
const CACHE_VERSION = 'v1';
const CACHE_NAME = `pytodo-${CACHE_VERSION}`;

self.addEventListener('activate', event => {
  // Delete old caches when new version activates
  event.waitUntil(
    caches.keys().then(names =>
      Promise.all(
        names
          .filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      )
    )
  );
});
```

When the app updates (new `CACHE_VERSION`), the old cache is purged and static assets are re-fetched. This ensures users always get the latest version of the web app without manual cache clearing.

## Offline Edit Queue

### How It Works

When the user makes a change while offline, the edit is serialized and stored in `localStorage`:

```javascript
// Queue structure in localStorage
{
  "pytodo_offline_queue": [
    {
      "id": "unique-edit-id",
      "timestamp": 1709500000000,
      "method": "PATCH",
      "url": "/api/items/6ba7b810-9dad-11d1-80b4-00c04fd430c8/toggle",
      "body": null
    },
    {
      "id": "unique-edit-id-2",
      "timestamp": 1709500001000,
      "method": "POST",
      "url": "/api/lists/550e8400-e29b-41d4-a716-446655440000/items",
      "body": { "reminder": "Call dentist", "priority": 1 }
    }
  ]
}
```

### Replay on Reconnect

When the network becomes available again:

```
┌──────────────┐    online event    ┌─────────────────┐
│  Offline     │───────────────────→│  Replay Queue   │
│  (queued     │                    │                 │
│   edits in   │                    │  for each edit: │
│   localStorage)                   │    → fetch(url) │
│              │                    │    → success?   │
│              │                    │      remove     │
│              │                    │    → fail?      │
│              │                    │      keep in    │
│              │                    │      queue      │
│              │                    │                 │
│              │                    │  Refresh UI     │
│              │                    │  after replay   │
└──────────────┘                    └─────────────────┘
```

The replay process:
1. Listen for the `online` event (or detect during polling)
2. Process queued edits in chronological order (FIFO)
3. For each edit: attempt the API call
4. On success: remove from queue, continue
5. On failure (409 Conflict, 404 Not Found): discard the edit, show user notification
6. After all edits replayed: full refresh from server

### Conflict Resolution

Conflicts can occur when:
- User completes an item on the phone (offline), and completes the same item on the desktop
- User edits an item on the phone (offline), and the item is deleted on the desktop

Resolution strategy: **server state wins** (last-writer-wins, same as P2P sync).

| Scenario | Phone (offline) | Desktop (online) | Resolution |
|----------|----------------|-------------------|------------|
| Both toggle same item | Complete item | Complete item | Server already has it completed — edit is a no-op |
| Edit vs delete | Edit reminder text | Delete item | Server returns 404 — edit is discarded |
| Both edit same field | Change to "Buy milk" | Change to "Buy bread" | Server has "Buy bread" — phone edit overwrites to "Buy milk" (LWW by timestamp) |
| Add vs add | Add "Call dentist" | Add "Pay bills" | Both items exist — no conflict |

The user is shown a brief notification when edits are discarded: "1 offline edit could not be applied (item was deleted)."

### Offline UI Indicators

When the web app detects it's offline:

```
┌─────────────────────────────┐
│  ⚠ Offline — changes will   │  ← Yellow banner at top
│    sync when reconnected    │
├─────────────────────────────┤
│                             │
│  (cached todo items shown)  │
│                             │
│  ☐ Buy groceries            │  ← Can still interact
│  ☐ Call dentist        [Q]  │  ← [Q] badge = queued change
│                             │
└─────────────────────────────┘
```

- Yellow offline banner at the top of the screen
- Queued edits show a small badge or visual indicator
- Items are still interactive (toggle, add, edit) — changes queue locally
- Banner disappears automatically when network returns

## PWA Installation Flow

### Android (Chrome)

1. User opens `http://192.168.1.5:8080` in Chrome
2. Chrome detects the manifest and service worker
3. After ~30 seconds of engagement, Chrome shows "Add to Home Screen" prompt
4. User taps "Add" → app icon appears on home screen
5. Launching from home screen opens in standalone mode (no address bar)

### iOS (Safari)

1. User opens `http://192.168.1.5:8080` in Safari
2. User taps Share → "Add to Home Screen"
3. App icon appears on home screen
4. Launching from home screen opens in standalone mode

Note: iOS PWA support has limitations:
- No push notifications
- Service worker may be evicted after 2 weeks of non-use
- No background sync API
- Limited to 50MB cached storage

These limitations are acceptable for a Phase 1 PWA. The app gracefully degrades — if the service worker is evicted, it re-registers on next launch and re-caches assets.

## Icons

The PWA requires multiple icon sizes for different platforms:

| Size | Purpose |
|------|---------|
| 192x192 | Android home screen, Chrome install |
| 512x512 | Android splash screen |
| 180x180 | iOS home screen (`apple-touch-icon`) |
| 32x32 | Favicon |

These are generated from the existing PyTodo-Qt icon at build time or included as static assets.

## Connection to the Broader Mobile Roadmap

This PWA work is Phase 2 of the Web UI but also connects to the strategic roadmap:

```
v0.3.11 Phase 5-6 (Web UI + PWA)
│
│  Provides: mobile web access on LAN, offline caching
│  Limitation: desktop must be running, same network
│
▼
v0.4.x (Server Mode — Strategic Phase 1)
│
│  Provides: headless server, runs on Raspberry Pi / NAS
│  The Web UI + PWA now works 24/7 without desktop
│  Tailscale/VPN enables access from anywhere
│
▼
v0.5.x (REST API + Collaboration — Strategic Phase 2)
│
│  Provides: full REST/WebSocket API, multi-user
│  PWA gets real-time updates via WebSocket
│  Collaboration features (shared lists, permissions)
│
▼
v0.6.x+ (Native Mobile — Strategic Phase 3)
│
│  Provides: native iOS/Android apps
│  PWA continues as fallback / lightweight option
│  Native apps use the same REST API
```

The PWA is not a dead end — it's the first step in a progressive mobile strategy:
1. **Today**: Web UI on LAN (Phase 5)
2. **This release**: PWA with offline (Phase 6)
3. **Next release**: Server mode makes PWA always available
4. **Future**: Native apps supplement (don't replace) the PWA

Even after native mobile apps exist, the PWA remains valuable as a zero-install option for new users, occasional-use devices, and platforms where native apps aren't available.

## Server-Side Requirements

### Manifest and Service Worker Headers

The aiohttp server must serve these files with specific headers:

```python
# manifest.json
response.content_type = "application/manifest+json"

# sw.js - CRITICAL: must be served from root scope
# Service worker scope is determined by its URL path
@routes.get("/sw.js")
async def serve_sw(request):
    return web.FileResponse(
        static_path / "sw.js",
        headers={"Content-Type": "application/javascript",
                 "Service-Worker-Allowed": "/"}
    )
```

The service worker must be served from the root path (`/sw.js`) to have scope over the entire app. If served from `/static/sw.js`, it would only control requests under `/static/`.

### Cache-Control Headers

```python
# Static assets: cache for 1 year (SW handles versioning)
if request.path.startswith("/static/"):
    response.headers["Cache-Control"] = "public, max-age=31536000"

# API responses: no cache (SW handles caching)
response.headers["Cache-Control"] = "no-cache"

# HTML: no cache (ensure SW updates are detected)
if request.path == "/":
    response.headers["Cache-Control"] = "no-cache"
```

## Testing Strategy

### Service Worker Tests

Service workers are difficult to unit test because they run in a browser context. The testing strategy:

1. **Logic extraction**: Extract caching logic and queue management into pure functions that can be tested with Node.js or in-browser test runners
2. **Integration tests**: Use the aiohttp test client to verify correct headers are set
3. **Manual testing**: Verify offline behavior in Chrome DevTools (Application → Service Workers → Offline checkbox)

### Offline Queue Tests (`tests/test_web_pwa.py`)

```python
# Test that offline edits are serialized correctly
# Test that queue replay processes edits in order
# Test that failed replays are handled gracefully
# Test that cache versioning clears old caches
```

These tests focus on the server-side behavior (correct headers, manifest serving) and the queue replay API behavior, not the browser-side service worker execution.

## Scope Boundaries

**In scope for v0.3.11 Phase 6:**
- Service worker with cache-first (static) and network-first (API) strategies
- Web app manifest with icons for Android and iOS
- Offline edit queue in localStorage with replay on reconnect
- Offline/online visual indicators
- PWA installability on Android Chrome and iOS Safari

**Not in scope:**
- Push notifications (requires a push server, planned for v0.4.x+)
- Background sync API (limited browser support, not critical)
- IndexedDB for large offline datasets (localStorage sufficient for todo data)
- Automatic conflict resolution UI (conflicts are resolved silently using LWW)
