# Web UI Architecture — Design Document

## Purpose

Add an embedded web server to pytodo-qt that serves a mobile-optimized single-page application. This is the most architecturally significant addition since the P2P sync layer, and the critical step that transforms pytodo-qt from a desktop-only app into one that can be accessed from any device on the local network.

For the first time, users will be able to check their todos from a phone, tablet, or any device with a browser — without creating an account, installing an app, or sending data to the cloud. The web UI talks directly to the running desktop app over the local network.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                   pytodo-qt process                       │
│                                                          │
│  ┌─────────────┐     signals     ┌──────────────────┐   │
│  │             │←────────────────│                  │   │
│  │ MainWindow  │                 │   WebServer      │   │
│  │  (PyQt6)    │────────────────→│   (aiohttp)      │   │
│  │             │  QTimer.single  │                  │   │
│  └──────┬──────┘   Shot(0,...)   └────────┬─────────┘   │
│         │                                 │             │
│         │         ┌──────────┐            │             │
│         └────────→│          │←───────────┘             │
│                   │ Database │                           │
│                   │ (in-mem) │                           │
│                   └─────┬────┘                           │
│                         │                                │
│                   ┌─────┴────┐                           │
│                   │  SQLite  │                           │
│                   │  (WAL)   │                           │
│                   └──────────┘                           │
│                                                          │
│         ┌─────────────────────────────────┐              │
│         │       qasync Event Loop         │              │
│         │  (bridges Qt + asyncio)         │              │
│         │                                 │              │
│         │  Qt events ←→ asyncio tasks     │              │
│         │  P2P server, sync queue,        │              │
│         │  web server all run here        │              │
│         └─────────────────────────────────┘              │
└──────────────────────────┬───────────────────────────────┘
                           │
                    HTTP on port 8080
                    (local network)
                           │
              ┌────────────┴────────────┐
              │                         │
        ┌─────┴──────┐          ┌──────┴───────┐
        │ Phone      │          │ Tablet /     │
        │ browser    │          │ other device │
        │ (mobile    │          │ (same        │
        │  optimized)│          │  interface)  │
        └────────────┘          └──────────────┘
```

### The Single-Thread Model

This is the key architectural insight that makes the web UI work cleanly:

pytodo-qt already uses `qasync` to bridge Qt's event loop with Python's `asyncio`. The P2P server (`AsyncServer`), sync queue (`SyncQueue`), and all network operations run as asyncio tasks on this single event loop. The web server is just another asyncio task on the same loop.

```
┌─────────────────────────────────────────────────────┐
│              qasync QEventLoop                       │
│                                                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │ Qt events│  │ P2P server│  │ aiohttp web      │ │
│  │ (UI,     │  │ (port     │  │ server (port     │ │
│  │  timers, │  │  5364)    │  │  8080)           │ │
│  │  signals)│  │           │  │                  │ │
│  └──────────┘  └───────────┘  └──────────────────┘ │
│                                                     │
│         All on one thread — no locks needed          │
└─────────────────────────────────────────────────────┘
```

Because everything runs on one thread:
- The web server can read the in-memory `Database` object directly — no thread safety issues
- Writes from the web server need to go through `QTimer.singleShot(0, ...)` to ensure they happen during Qt's event dispatch (not mid-signal-handler)
- No mutexes, no thread pools, no race conditions
- The same model that makes P2P sync safe makes the web server safe

### What if the Event Loop is Blocked?

The single-thread model means a long-running synchronous operation on either side (Qt or asyncio) blocks the other. In practice this is not an issue because:

1. All I/O is async (network reads/writes, database operations are fast in-memory)
2. Qt operations are event-driven (no blocking dialogs during normal operation)
3. The P2P sync operations are already async and work fine alongside Qt — the web server is architecturally identical

## Technology Selection

### Why aiohttp (Not FastAPI, Flask, or Others)

| Framework | Async Native | Needs ASGI Server | Event Loop Integration | Dependency Weight |
|-----------|-------------|-------------------|----------------------|-------------------|
| **aiohttp** | Yes | No (self-contained) | Runs directly on asyncio | Medium (aiohttp only) |
| FastAPI | Yes | Yes (requires uvicorn) | Needs its own event loop or ASGI adapter | Heavy (fastapi + uvicorn + starlette + pydantic) |
| Flask | No | No (WSGI, needs thread) | Requires separate thread + thread-safe access | Light but wrong model |
| Tornado | Yes | No | Has its own IOLoop (conflicts with qasync) | Medium |
| Starlette | Yes | Yes (requires uvicorn) | Same issues as FastAPI | Medium |

**aiohttp wins because:**

1. **Native asyncio**: aiohttp's `web.Application` runs directly on any asyncio event loop. No ASGI server needed. We call `web.TCPSite(runner, host, port)` and `await site.start()` — it becomes an asyncio task on the existing `qasync` loop. FastAPI requires uvicorn, which wants to own the event loop.

2. **No extra dependencies**: aiohttp is a single package. FastAPI pulls in uvicorn, starlette, pydantic, typing-extensions, and more. For an embedded web server in a desktop app, minimal dependencies are important for packaging (PyInstaller) and startup time.

3. **Proven pattern**: The existing P2P `AsyncServer` already runs as an asyncio task on qasync. The web server follows the exact same pattern — `asyncio.ensure_future(web_server.start())`. No new architectural concepts.

4. **Flask is the wrong model**: Flask is WSGI (synchronous). Running it alongside Qt would require a separate thread, which means the web server can't safely access the in-memory Database. Thread-safe access to Qt objects is notoriously fragile. The async model avoids this entirely.

5. **Maturity**: aiohttp has been production-grade since 2014. It handles HTTP/1.1, WebSocket, static file serving, and middleware. It's used by large projects (Home Assistant, for example — the exact audience pytodo-qt targets).

### Why Pure HTML/CSS/JS (Not React, Vue, Svelte, etc.)

The web frontend is intentionally built without a JavaScript framework:

1. **No build step**: The HTML, CSS, and JS files are served directly from disk. No webpack, no npm, no node_modules, no compilation. This means:
   - The files are included in the Python package as static assets
   - PyInstaller bundles them without special configuration
   - Development is edit-refresh, no build toolchain

2. **Bundle size**: A framework-based SPA is 100KB-1MB+ minified. Pure HTML/CSS/JS for a todo app is <20KB total. On a mobile device over WiFi, this loads instantly.

3. **Maintainability**: The web UI is a secondary interface — the desktop app is primary. A framework would add a parallel tech stack (npm, node, build configs, type checking) that doubles the maintenance burden. Vanilla JS with `fetch()` is simple, readable, and needs no updates when framework versions change.

4. **Scope**: The web UI needs to display lists, show items with checkboxes, and handle basic CRUD. This is <500 lines of JS. A framework is overkill for this scope.

5. **PWA compatibility**: Service workers, web app manifests, and offline storage are all native browser APIs. No framework needed.

## REST API Design

### Endpoints

```
GET    /                          → Serve index.html
GET    /static/{path}             → Serve static assets

GET    /api/lists                 → All lists with item counts
GET    /api/lists/{list_id}       → Single list with all items
POST   /api/lists                 → Create new list
PUT    /api/lists/{list_id}       → Rename list
DELETE /api/lists/{list_id}       → Soft-delete list

POST   /api/lists/{list_id}/items → Add item to list
PUT    /api/items/{item_id}       → Update item fields
DELETE /api/items/{item_id}       → Soft-delete item
PATCH  /api/items/{item_id}/toggle → Toggle completion

GET    /api/status                → App info (version, sync state)
```

### Response Format

All API responses return JSON:

```json
{
  "lists": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Shopping",
      "item_count": 12,
      "completed_count": 5,
      "is_private": false
    }
  ]
}
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Shopping",
  "items": [
    {
      "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "reminder": "Buy milk",
      "priority": 2,
      "complete": false,
      "due_date": "2026-03-15",
      "due_time": "14:30:00",
      "tags": ["@errands", "@quick"],
      "time_spent": 0,
      "is_recurring": true,
      "created_at": 1709500000000,
      "updated_at": 1709500000000
    }
  ]
}
```

### Private Lists

Private lists (encrypted) are **excluded** from the Web UI API. The web server does not have access to the encryption keys, and serving private data over HTTP (even on LAN) would undermine the privacy guarantee. Private lists are simply omitted from `GET /api/lists` results.

### Error Responses

```json
{
  "error": "List not found",
  "status": 404
}
```

Standard HTTP status codes: 200 (OK), 201 (Created), 400 (Bad Request), 404 (Not Found), 500 (Internal Error).

## Data Flow

### Reads (Web → Database)

```
Phone browser                    aiohttp handler            Database
     │                                │                        │
     │  GET /api/lists/{id}          │                        │
     │──────────────────────────────→│                        │
     │                                │  database.get_list(id) │
     │                                │───────────────────────→│
     │                                │                        │
     │                                │←───────────────────────│
     │                                │  TodoList object       │
     │                                │                        │
     │                                │  Serialize to JSON     │
     │  JSON response                 │                        │
     │←──────────────────────────────│                        │
```

Reads are straightforward: the aiohttp handler calls Database methods directly (same thread, same event loop) and serializes the result to JSON.

### Writes (Web → Database → Desktop Refresh)

```
Phone browser          aiohttp handler         Database        MainWindow
     │                       │                    │                │
     │  PATCH /toggle/{id}  │                    │                │
     │─────────────────────→│                    │                │
     │                       │  Find item         │                │
     │                       │───────────────────→│                │
     │                       │←───────────────────│                │
     │                       │                    │                │
     │                       │  item.complete =   │                │
     │                       │    not complete     │                │
     │                       │  item.mark_updated()│                │
     │                       │  database.save()   │                │
     │                       │───────────────────→│                │
     │                       │                    │                │
     │                       │  QTimer.singleShot │                │
     │                       │  (0, refresh_ui)   │                │
     │                       │────────────────────────────────────→│
     │                       │                    │                │
     │  200 OK               │                    │     (UI updates│
     │←─────────────────────│                    │      on next   │
     │                       │                    │      event     │
     │                       │                    │      cycle)    │
```

The write path has a critical detail: after modifying the Database, the web handler schedules a UI refresh via `QTimer.singleShot(0, main_window._refresh_ui)`. This ensures:
1. The refresh happens during Qt's event dispatch (not inside an asyncio handler)
2. All Qt signal/slot mechanisms work correctly
3. The desktop UI updates to reflect the change made from the phone

### Why Not Use the Undo Stack for Web Writes?

The web API bypasses `QUndoStack` deliberately. This is consistent with how P2P sync works — remote changes (from sync or web) are applied directly to the Database without creating undo commands. Rationale:

1. The undo stack is a desktop-session concept — undoing a change made from a phone doesn't make UX sense
2. P2P sync already bypasses the undo stack using the same pattern
3. Undo commands capture specific field values by UUID, which would conflict with external changes
4. Web changes use `mark_updated()` for LWW, which is the same mechanism sync uses

## Live Updates

### Polling vs WebSocket vs Server-Sent Events

| Approach | Complexity | Browser Support | Battery Impact | Implementation |
|----------|-----------|----------------|---------------|----------------|
| **Polling (3s)** | Low | Universal | Moderate | `setInterval(fetch, 3000)` |
| WebSocket | High | Universal | Low | Requires connection management |
| SSE | Medium | Universal | Low | Requires event stream API |

**Polling is chosen for Phase 1** because:
- Simplest implementation on both server and client
- No connection state to manage (HTTP is stateless)
- 3-second interval is responsive enough for a todo app
- Low risk of bugs from dropped connections, reconnection logic
- Battery impact is minimal (small JSON payloads over WiFi)

WebSocket or SSE can be added in a future version if real-time responsiveness becomes important (e.g., collaborative editing in Phase 2 of the strategic roadmap).

### Efficient Polling

To avoid re-rendering unchanged data, the polling mechanism uses timestamps:

```
GET /api/lists/{id}?since=1709500000000
```

If no items have `updated_at` > `since`, the server returns `304 Not Modified`. The client only re-renders when data has actually changed.

## Mobile Frontend Design

### Layout

```
┌─────────────────────────────┐
│  PyTodo-Qt        ☰  ⚙     │  ← Header: app name, menu, settings
├─────────────────────────────┤
│                             │
│  ┌─────────────────────┐   │
│  │ + Add new item...   │   │  ← Quick add input
│  └─────────────────────┘   │
│                             │
│  ┌─────────────────────┐   │
│  │ ☐ Buy groceries     │   │  ← Item row: checkbox + text
│  │   📅 Today 2:30 PM  │   │  ← Due date/time badge
│  │   @errands @quick    │   │  ← Tag chips
│  └─────────────────────┘   │
│                             │
│  ┌─────────────────────┐   │
│  │ ☑ Write report      │   │  ← Completed item (strikethrough)
│  │   📅 Yesterday      │   │
│  └─────────────────────┘   │
│                             │
│  ┌─────────────────────┐   │
│  │ ☐ Call dentist  ⚡   │   │  ← High priority indicator
│  │   📅 Tomorrow       │   │
│  └─────────────────────┘   │
│                             │
├─────────────────────────────┤
│  📋 Lists  │  ➕ Add  │  ⚙  │  ← Bottom nav (thumb-friendly)
└─────────────────────────────┘
```

### Design Principles

1. **Touch-first**: 44px minimum touch targets (Apple HIG recommendation). No hover states. Tap and swipe interactions.

2. **Bottom navigation**: Primary actions at the bottom of the screen, reachable by thumb. Top area for passive display (header, status).

3. **System theme**: Respects `prefers-color-scheme` media query for automatic light/dark mode matching the phone's system setting.

4. **System fonts**: Uses the system font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, ...`) for native feel and zero font loading.

5. **Progressive enhancement**: Core functionality (view lists, toggle items) works without JavaScript. JS adds polish (inline editing, animations, polling).

6. **Minimal payload**: Target <20KB total for HTML + CSS + JS. No external CDN dependencies. Everything served from the embedded server.

### Interactions

| Action | Gesture | API Call |
|--------|---------|----------|
| Toggle completion | Tap checkbox | `PATCH /api/items/{id}/toggle` |
| Add item | Type in input, press Enter | `POST /api/lists/{id}/items` |
| Switch list | Tap list in bottom nav | `GET /api/lists/{id}` |
| Edit item | Tap item text | Inline edit → `PUT /api/items/{id}` |
| Delete item | Swipe left (or long press) | `DELETE /api/items/{id}` |
| Set priority | Tap priority badge | Cycle through High/Normal/Low |
| Pull to refresh | Pull down | `GET /api/lists/{id}` |

## Configuration

```python
@dataclass
class WebConfig:
    enabled: bool = False    # Disabled by default
    port: int = 8080         # HTTP port
```

### CLI Arguments

```
--web yes|no          Enable/disable web UI
--web-port PORT       Web server port (default: 8080)
```

### Settings Dialog — Web UI Tab

```
┌─────────────────────────────────────────────┐
│  Web UI                                     │
│  ┌───────────────────────────────────────┐  │
│  │ ☑ Enable Web UI                       │  │
│  │                                       │  │
│  │ Port: [8080  ▾]                       │  │
│  │                                       │  │
│  │ Status: Running                       │  │
│  │ URL: http://192.168.1.5:8080         │  │
│  │                                       │  │
│  │ Scan QR code to open on phone:       │  │
│  │ ┌───────────┐                        │  │
│  │ │ █▀▀▀▀▀█   │                        │  │
│  │ │ █ QR  █   │  (optional, nice UX)   │  │
│  │ │ █▄▄▄▄▄█   │                        │  │
│  │ └───────────┘                        │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

The QR code is a nice-to-have that eliminates the need to type the URL on the phone. Generated using a pure-Python QR library or inline SVG generation (no additional dependency needed — can use a simple QR code algorithm or defer to future).

## Security Model (Phase 1)

### LAN-Only, No Authentication

Phase 1 operates on a trust-the-local-network model:
- Web server binds to `0.0.0.0:8080` (all interfaces)
- No authentication required
- Accessible to anyone on the same network

This is acceptable for Phase 1 because:
1. Home networks are generally trusted
2. The data is todo items, not financial or medical records
3. This matches how many self-hosted apps work initially (Home Assistant, Jellyfin, etc.)
4. Authentication is planned for server mode (v0.4.x)

### Mitigations

- Private (encrypted) lists are excluded from the API entirely
- The web server is disabled by default — users opt in
- Status bar shows when the web server is active
- Web UI is read-write for non-private lists only

### Future Security (v0.4.x Server Mode)

Phase 1 of the strategic roadmap (server mode) will add:
- TLS encryption
- Session-based authentication (Argon2id password hashing)
- Rate limiting
- CSRF protection for the web UI
- CSP headers

## Status Bar Integration

When the web server is active, the status bar shows the URL:

```
[███████  45%] | Lists: 3 | Current: 5/12 | ... | Web: 192.168.1.5:8080 | Server: 0.0.0.0:5364
```

The `web_status_label` follows the same pattern as `server_status_label`:
- Green text when running: `"Web: 192.168.1.5:8080"`
- Gray text when off: `"Web: Off"`

## File Structure

```
src/pytodo_qt/web/
├── __init__.py          # Package init, public API
├── server.py            # WebServer class: lifecycle, aiohttp setup
├── api.py               # Route handlers: list/item CRUD, toggle, status
└── static/
    ├── index.html       # SPA shell, bottom nav, list/item views
    ├── style.css        # Mobile-first responsive styles
    └── app.js           # fetch() API client, state management, polling
```

The `static/` directory is included in `pyproject.toml` package data so it's bundled with the Python package and PyInstaller builds.

## Lifecycle

### Startup

```python
# In MainWindow.__init__ or _init_components:
if self._config.web.enabled:
    from ..web.server import WebServer
    self._web_server = WebServer(self._database, self, self._config.web)
    asyncio.ensure_future(self._web_server.start(
        host="0.0.0.0",
        port=self._config.web.port
    ))
    self._status_bar.set_web_status(True, local_ip, self._config.web.port)
```

### Shutdown

```python
# In MainWindow.closeEvent:
if self._web_server:
    asyncio.ensure_future(self._web_server.stop())
```

### Toggle via Menu

Tools menu → "Web UI" checkbox:
- On: start server, show URL in status bar
- Off: stop server, update status bar

## Testing Strategy

### API Tests (`tests/test_web_api.py`)

Using `aiohttp.test_utils.TestClient`:

```python
async def test_get_lists(aiohttp_client):
    # Create test database with known lists
    # Create aiohttp app with test database
    client = await aiohttp_client(app)
    resp = await client.get("/api/lists")
    assert resp.status == 200
    data = await resp.json()
    assert len(data["lists"]) == 2
```

Test categories:
- List CRUD (create, read, update, delete)
- Item CRUD (create, read, update, delete)
- Toggle completion
- Private list exclusion
- Error handling (404, 400)
- Status endpoint
- Static file serving
