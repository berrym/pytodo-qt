# v0.3.11 Pre-Release Plan

**Status:** In progress (as of 2026-03-16)
**Goal:** Make the web UI a trustworthy, real-world-usable mobile client before packaging and releasing.

---

## Philosophy

- **Data integrity first** — no point packaging something that loses user data
- **No manual version bumps** — `pyproject.toml` is source of truth for pip/PyPI; release artifact naming uses the git tag via `gh release create`
- **Pre-releases are real builds** — each `v0.3.11-preN` tag triggers CI, produces full artifacts in new packaging formats (AppImage, DMG, installer)
- **Packaging upgrades land before pre1** — so the first pre-release artifacts are already in the final formats
- **Manual testing required** — every pre-release build must be manually verified before the tag is promoted to final
- **Windows is best-effort** — CI builds and tests pass; manual verification deferred unless a Windows machine is available

---

## Phase 1: Data Integrity — Offline & Sync Safety

The critical gap. Without this, the web UI cannot be trusted with real data.

### 1A. Conflict Guards (Server Side)

Add `updated_at` / ETag-style validation to all write endpoints in `web/api.py`.

- Every `PUT`, `PATCH`, `DELETE` that modifies an item or list checks the client-provided `updated_at` against the current server value
- If the client's value is stale → **409 Conflict** with the current server state in the response body
- Client can force-write by including `force: true` in the request (user explicitly chose to overwrite)
- Force-write shows a warning in the UI: "This will overwrite newer changes. Are you sure?"
- This protects **all** clients (desktop P2P sync, web, future server mode)
- Must verify existing desktop P2P sync (LWW merge in MainWindow, DeviceManagerDialog, PeerManagerDialog) still works correctly — the conflict guards are for the web API layer, not the P2P merge layer

### 1B. Offline Write Replay (Client Side)

The IndexedDB queue in `app.js` stores pending operations but never replays them.

- On reconnect (WebSocket open or polling success after failure): replay queued ops sequentially
- Each replayed op checks the response:
  - **200/201**: Success → remove from queue, apply server state
  - **409 Conflict**: Fetch fresh state, show conflict toast with options:
    - "Keep server version" (discard local change)
    - "Force my version" (re-send with `force: true`)
    - "View diff" (show what changed — stretch goal, may defer)
  - **Other errors**: Keep in queue, retry on next reconnect
- Queue is visible and clearable in Settings (already exists in UI)
- Pending count badge already exists — make sure it updates accurately

### 1C. WebSocket Push

Replace 3-second polling with real-time event stream.

- aiohttp native WebSocket at `/ws`
- Server broadcasts events: `item_changed`, `item_deleted`, `list_changed`, `columns_changed`, `sort_changed`
- Each event includes the full updated object (not just ID) so the client can update in place
- Client subscribes on page load, reconnects with exponential backoff on disconnect
- Falls back to polling if WebSocket connection fails (e.g., reverse proxy doesn't support WS)
- Instant offline detection: "Connection lost" banner appears the moment the socket closes
- Desktop side: `_schedule_save_and_refresh()` (the Qt→aiohttp bridge) also broadcasts to WS clients

### 1D. Offline Indicators

Small UI work, big trust payoff.

- Connection status dot in header: green (connected), amber (pending changes), red (offline)
- "Last synced: Xm ago" text near status dot
- "N changes pending" badge (already partially exists)
- When offline: banner at top "You're offline — changes will sync when reconnected"

---

## Phase 2: Interop Verification

Before moving to packaging, verify the new conflict guards and WebSocket layer don't break anything.

- Desktop-to-desktop P2P sync still works (LWW merge, not affected by web API guards, but verify)
- Desktop + web simultaneous editing (both clients open, edits on both, verify convergence)
- Web offline → edits → reconnect → replay (the core new flow)
- Multi-web-client scenario (two browser tabs, verify WS broadcast)
- Auto-sync scheduler (`gui/auto_sync.py`) + WebSocket coexistence
- Kanban board column changes sync correctly (column renames, WIP limits, layout presets)
- Recurring task auto-advance interop (desktop advances, web sees it; web completes, desktop sees advance)

---

## Phase 3: Packaging Upgrades

Now there's something worth packaging.

### Linux
- **Keep**: tar.gz with install.sh (existing)
- **Add**: AppImage via `appimagetool` — uses existing PyInstaller onedir output as AppDir, existing `.desktop` file and icon from `packaging/linux/`

### macOS
- **Upgrade**: zip → DMG via `create-dmg` or `hdiutil`
- Background image, Applications symlink for drag-install
- Ad-hoc signing already in place

### Windows
- **Upgrade**: zip → NSIS or Inno Setup installer
- Keep zip as portable option
- CI builds it; manual testing deferred unless Windows machine available

### Version Handling
- `pyproject.toml` remains source of truth (PEP compliant, pip/PyPI)
- Release artifact naming uses git tag (workflow already strips `v` prefix)
- No more manual version bumps in `settings.py`, `spec`, `release.yml` — derive from `pyproject.toml` or tag at build time

---

## Phase 4: Pre-Release Cycle

- Tag `v0.3.11-pre1` via `gh release create v0.3.11-pre1 --prerelease`
- CI builds all artifacts (AppImage, DMG, installer, tar.gz, zip)
- Manual testing:
  - Linux: AppImage + tar.gz on real machine
  - macOS: DMG on both arm64 and x86_64 if possible
  - Windows: Best-effort via CI passing; manual test if machine available
  - Web: Real devices (iPhone Safari, Android Chrome, tablet)
- Fix issues → `pre2`, `pre3` as needed
- Each pre-release is a real GitHub release with downloadable artifacts

---

## Phase 5: Polish (Between Pre-Releases)

Cherry-pick based on what surfaces from manual testing and what feels right:

- Smart add quick action buttons (priority, date picker, tag)
- Column selector for board view new items
- Board "All done!" empty state
- Tablet split-view (list picker sidebar + content)
- Any UX issues found during manual testing

---

## Phase 6: Final Release

- Tag `v0.3.11` (no prerelease flag)
- `publish.yml` pushes to PyPI
- Release notes covering the full v0.3.11 scope (web UI, sort, kanban, offline, sync, packaging)
- This is the last PyQt6 release before the 0.4.x PySide6 era

---

## Design Decisions Log

### Conflict Model: Pessimistic with Escape Hatch
- Default: reject stale writes (409), force client to fetch fresh state
- Escape: user can explicitly force-write after warning ("This will overwrite newer changes")
- Rationale: simpler to reason about than optimistic merge; silent merges are worse than visible conflicts; but power users who know what they want should be able to override

### WebSocket vs SSE
- WebSocket chosen over SSE because aiohttp has native WS support, and we may want bidirectional communication in the future (e.g., typing indicators, presence)
- SSE would be simpler but one-directional

### Offline Queue Replay Strategy
- Sequential replay (not parallel) — order matters for dependent operations
- 409 handling with user choice — never silently discard or silently overwrite
- Queue persists across page reloads (IndexedDB)
