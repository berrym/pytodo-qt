# Mobile Access for pytodo-qt

## The Problem

pytodo-qt is built with PyQt6, which provides an excellent cross-platform desktop experience (Linux, macOS, Windows). While **PyQt6/PySide6 have experimental mobile support** (iOS via static builds, Android via Qt for Android), this support is limited and not well-documented for Python bindings.

This creates a real usability gap:
- Users can sync between desktop/laptop devices
- Users cannot access their todos on phones or tablets
- Mobile is where people often need quick todo access (on the go, in stores, commuting)

Without mobile access, pytodo-qt is limited to "at the desk" usage, which significantly reduces its practical value as a daily-use todo app.

## Goals

1. Enable mobile access to pytodo-qt data
2. Maintain sync capability between desktop and mobile
3. Minimize development effort (we're not building a separate mobile app from scratch)
4. Provide something usable quickly, then iterate

## Options Evaluated

### Option 1: Web UI Mode (Recommended First Step)

**Approach:** Add a web server to pytodo-qt that serves a mobile-friendly interface.

```
┌─────────────────────┐
│  pytodo-qt desktop  │
│  (existing app)     │
│         +           │
│  embedded web server│
│  (new component)    │
└──────────┬──────────┘
           │ HTTP on local network
           ▼
┌─────────────────────┐
│  Phone browser      │
│  Mobile-optimized   │
│  web interface      │
└─────────────────────┘
```

**Pros:**
- Reuses existing database and logic completely
- No new app to build, distribute, or maintain
- Works on any phone with a browser
- Changes sync immediately (same database)
- Moderate development effort

**Cons:**
- Requires same network (home wifi) for basic setup
- Not truly offline on mobile
- Depends on desktop running

**Effort:** ~2-3 days for basic implementation

**Tech stack:**
- Flask or FastAPI for web server
- Simple HTML/CSS/JS (no framework needed initially)
- Mobile-first responsive design

### Option 2: PWA Enhancement

**Approach:** Extend Option 1 with Progressive Web App features.

**Additional capabilities:**
- Service worker for offline caching
- "Add to Home Screen" on phones
- Background sync when connection restored

**Pros:**
- True offline capability on mobile
- Feels more like a native app
- Still web-based, no app store

**Cons:**
- More frontend complexity
- Need to handle offline/online state
- Sync conflicts more likely

**Effort:** Additional 2-3 days on top of Option 1

### Option 3: Remote Access (Tailscale/ZeroTier)

**Approach:** Use mesh VPN for access outside home network.

**How it works:**
- Install Tailscale on desktop and phone
- Desktop pytodo-qt accessible from anywhere
- Secure, encrypted connection

**Pros:**
- Works from anywhere, not just home wifi
- No port forwarding or relay servers
- Free tier sufficient for personal use

**Cons:**
- Requires Tailscale/ZeroTier setup
- Extra app on phone
- Desktop must be running

**Effort:** Documentation only (user setup), works with Option 1

### Option 4: BeeWare Native Mobile

**Approach:** Build native iOS/Android apps using BeeWare (Python).

**Architecture:**
```
┌──────────────────┐     ┌──────────────────┐
│ pytodo-qt        │     │ pytodo-mobile    │
│ (PyQt6 desktop)  │     │ (Toga mobile)    │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         └──────────┬─────────────┘
                    ▼
         ┌──────────────────┐
         │ shared library   │
         │ (models, sync,   │
         │  crypto, db)     │
         └──────────────────┘
```

**Pros:**
- True native mobile apps
- Full offline support
- Best mobile UX

**Cons:**
- Significant effort (new UI layer)
- App store distribution complexity
- Two codebases to maintain

**Effort:** 2-4 weeks minimum

### Option 5: Native Mobile (Flutter/React Native/Swift/Kotlin)

**Approach:** Build mobile apps in mobile-native technologies.

**Pros:**
- Best possible mobile experience
- Large ecosystem, good tooling

**Cons:**
- Complete rewrite of UI and logic
- Different language/framework
- Highest effort by far

**Effort:** Months

### Option 6: PyQt6/PySide6 Mobile (Experimental)

**Approach:** Deploy the existing PyQt6 codebase to mobile using Qt for Android/iOS.

**How it works:**
- PySide6 has experimental support for Android via `pyside6-android-deploy`
- Qt for Android provides the underlying framework
- Requires building Python + Qt as static libraries for mobile
- Same codebase could theoretically run on desktop and mobile

**Architecture:**
```
┌──────────────────────────────────┐
│        pytodo-qt codebase        │
│   (PyQt6 or PySide6 widgets)     │
└────────────────┬─────────────────┘
                 │
    ┌────────────┼────────────────┐
    ▼            ▼                ▼
┌────────┐  ┌─────────┐  ┌─────────────┐
│Desktop │  │ Android │  │ iOS (static)│
│(normal)│  │ (APK)   │  │ (limited)   │
└────────┘  └─────────┘  └─────────────┘
```

**Pros:**
- Single codebase for desktop and mobile
- Reuses all existing code, models, sync logic
- No new UI framework to learn
- Full offline support (native app)

**Cons:**
- Experimental/limited documentation for Python bindings
- PySide6 (LGPL) better supported than PyQt6 (GPL) for mobile
- May require codebase migration from PyQt6 to PySide6
- Touch targets and UI would need mobile adaptation
- Build process is complex (cross-compilation, static linking)
- App size likely large (bundled Python + Qt)
- iOS support more limited than Android

**Current status (as of 2025):**
- PySide6 6.5+ includes `pyside6-android-deploy` tool
- Android deployment works but requires specific Qt/Python versions
- iOS requires manual static builds, less tooling support
- Community examples exist but production use is rare

**Effort:** 1-2 weeks for Android prototype, uncertain for iOS

**When to consider:**
- If web-based approach (Options 1-2) proves insufficient
- If maintaining two codebases (Option 4-5) is too costly
- Once PySide6 mobile tooling matures further

## Recommended Path

### Phase 1: Web UI Mode (Immediate)

Implement Option 1 - embedded web server with mobile-friendly interface.

**Scope:**
- Add FastAPI/Flask web server as optional mode
- Create simple, mobile-optimized HTML interface
- Basic CRUD: view lists, view items, toggle complete, add item
- Menu option or command-line flag to enable

**Non-goals for Phase 1:**
- Offline support (defer to Phase 2)
- Remote access (document Tailscale as user option)
- Full feature parity with desktop

### Phase 2: PWA Offline (Near-term)

Enhance with Progressive Web App features:
- Service worker for offline caching
- Local storage for offline edits
- Sync queue for when connection restored

### Phase 3: Remote Access Documentation

Document how users can set up Tailscale/ZeroTier for access outside home network. No code changes needed.

### Phase 4: Evaluate Native Mobile (Future)

Once web UI is proven and usage patterns understood, evaluate whether native mobile apps are worth the investment. Options include:
- BeeWare/Toga (Option 4) - Python with native widgets
- PySide6 mobile (Option 6) - Same codebase, experimental tooling
- Flutter/React Native (Option 5) - Complete rewrite, best mobile UX

## Technical Notes

### Web Server Integration

The web server should:
- Run in a separate thread or async loop
- Share the same `DatabaseStorage` instance
- Be optional (disabled by default or toggleable)
- Use a non-privileged port (e.g., 8080)

### API Design

Simple REST API:
```
GET  /api/lists              - List all lists
GET  /api/lists/:id          - Get list with items
POST /api/lists              - Create list
PUT  /api/lists/:id          - Update list
DELETE /api/lists/:id        - Delete list

GET  /api/lists/:id/items    - Get items for list
POST /api/lists/:id/items    - Add item
PUT  /api/items/:id          - Update item
DELETE /api/items/:id        - Delete item
```

### Mobile UI Considerations

- Large touch targets (44px minimum)
- Simple, focused interface
- Swipe gestures for common actions
- Pull-to-refresh for sync
- Bottom navigation (thumb-friendly)

## Success Criteria

**Phase 1 complete when:**
- [ ] Can view lists and items on phone browser
- [ ] Can toggle item completion
- [ ] Can add new items
- [ ] Works on home wifi
- [ ] Responsive design works on various phone sizes

**Phase 2 complete when:**
- [ ] PWA installable on phone home screen
- [ ] Basic offline viewing works
- [ ] Edits made offline sync when reconnected

## Not In Scope

The following are explicitly not goals for mobile access:
- Full feature parity with desktop (mobile should be focused/simplified)
- App store distribution (web-based approach avoids this)
- Multi-user features (same single-user model as desktop)
- Building a "platform" (this is pragmatic mobile access, not architecture)
