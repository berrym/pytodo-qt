# macOS Build and Code Signing Guide

This document details the challenges and solutions for building and signing PyQt6 applications for macOS distribution via GitHub Actions without a paid Apple Developer account.

## The Problem

Building PyQt6 applications with PyInstaller for macOS distribution is notoriously difficult due to:

1. **Code signing requirements** - macOS requires all executables to be signed
2. **Gatekeeper** - Blocks apps from "unidentified developers"
3. **Qt 6.5+ permission plugins** - Cause crashes during static initialization
4. **Bundle structure** - PyInstaller bundles have complex nested frameworks

### The Specific Crash

When running a PyInstaller-built PyQt6 app on macOS, you may encounter:

```
EXC_BAD_ACCESS (SIGSEGV) in _CFGetNonObjCTypeID
```

Stack trace typically shows:
```
CFBundleCopyBundleURL
QLibraryInfoPrivate::paths
_GLOBAL__sub_I_qdarwinpermissionplugin_location.mm
```

This crash occurs because Qt 6.5+ includes "Darwin permission plugins" that attempt to access the app's bundle URL during C++ static initialization—before any Python code runs. In an ad-hoc signed bundle, `CFBundleGetMainBundle()` may return NULL, causing a segmentation fault.

## The Solution

### 1. Delete the Crashing Permission Plugins

The most reliable fix is to delete the Qt permission plugin `.dylib` files after PyInstaller builds the app but before signing:

```yaml
- name: Delete crashing Qt permission plugins (macOS)
  if: runner.os == 'macOS'
  run: |
    find dist/YourApp.app -name "libqdarwinpermissionplugin_location.dylib" -delete
    find dist/YourApp.app -name "libqdarwinpermissionplugin_camera.dylib" -delete
    find dist/YourApp.app -name "libqdarwinpermissionplugin_microphone.dylib" -delete
    find dist/YourApp.app -name "libqdarwinpermissionplugin_bluetooth.dylib" -delete
    find dist/YourApp.app -name "libqdarwinpermissionplugin_contacts.dylib" -delete
    find dist/YourApp.app -name "libqdarwinpermissionplugin_calendar.dylib" -delete
```

**Note:** Only delete these if your app doesn't need location, camera, microphone, etc. Most desktop apps don't.

### 2. Create Entitlements File

Create `entitlements.plist` for Python compatibility with Hardened Runtime:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Required if using Hardened Runtime with Python -->
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
```

### 3. Proper Ad-Hoc Signing

The signing process must:
1. Clear extended attributes
2. Remove existing signatures
3. Apply fresh ad-hoc signature with hardened runtime

```yaml
- name: Ad-hoc sign application (macOS)
  if: runner.os == 'macOS'
  run: |
    # 1. Remove extended attributes that can cause signing issues
    xattr -rc dist/YourApp.app

    # 2. Remove existing signatures (PyInstaller signs by default)
    find dist/YourApp.app -name "_CodeSignature" -exec rm -rf {} +

    # 3. Apply fresh ad-hoc signature with hardened runtime
    codesign --force --deep --sign - \
      --options runtime \
      --entitlements entitlements.plist \
      dist/YourApp.app

    # 4. Verify signature
    codesign --verify --verbose --deep dist/YourApp.app
```

### 4. PyInstaller Spec File Configuration

Ensure your `.spec` file includes proper macOS bundle configuration:

```python
app = BUNDLE(
    coll,
    name='YourApp.app',
    icon='icon.icns',
    bundle_identifier='com.yourname.yourapp',  # Reverse-DNS format
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        # Privacy descriptions (even if not using these features)
        'NSLocationWhenInUseUsageDescription': 'Required for Qt Location services.',
        'NSCameraUsageDescription': 'Access needed for photos.',
        'NSMicrophoneUsageDescription': 'Access needed for audio.',
        'LSEnvironment': {
            'QT_MAC_WANTS_LAYER': '1',
        },
    },
)
```

### 5. Use `--onedir` Mode

Always use `--onedir` (not `--onefile`) for macOS PyQt6 apps:
- `--onefile` causes signature and path-related segfaults
- `--onedir` creates a proper `.app` bundle structure

## Complete GitHub Actions Workflow

```yaml
name: Build Release

on:
  release:
    types: [published]
  workflow_dispatch:

jobs:
  build:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install pyinstaller
          pip install .

      - name: Build with PyInstaller
        run: pyinstaller --noconfirm yourapp.spec

      - name: Delete crashing Qt permission plugins
        run: |
          find dist/YourApp.app -name "libqdarwinpermissionplugin_*.dylib" -delete

      - name: Ad-hoc sign application
        run: |
          xattr -rc dist/YourApp.app
          find dist/YourApp.app -name "_CodeSignature" -exec rm -rf {} +
          codesign --force --deep --sign - \
            --options runtime \
            --entitlements entitlements.plist \
            dist/YourApp.app
          codesign --verify --verbose --deep dist/YourApp.app

      - name: Package
        run: |
          cd dist
          zip -r ../YourApp-macos.zip YourApp.app

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: YourApp-macos
          path: YourApp-macos.zip
```

## Key Technical Details

### Ad-Hoc Signing (`-`)

- Uses a hyphen (`-`) as the signing identity
- Creates a cryptographic hash without Apple identity verification
- App will show "unidentified developer" warning on user's machine
- Sufficient for running on macOS, but users must bypass Gatekeeper

### The `--deep` Flag

- **Critical** for PyInstaller builds
- Recursively signs all nested `.dylib`, `.so`, and framework files
- PyQt6 bundles contain many internal libraries that must all be signed

### The `--options runtime` Flag

- Enables Hardened Runtime (required for modern macOS apps)
- Must be paired with entitlements that allow Python's dynamic features

### Why Deleting Plugins Works

The `libqdarwinpermissionplugin_*.dylib` files are Qt 6.5+ additions that:
1. Run during C++ static initialization (before Python starts)
2. Call `CFBundleCopyBundleURL(CFBundleGetMainBundle())`
3. Crash if the bundle isn't "fully recognized" by macOS

Since these plugins are optional and most apps don't need location/camera/etc., deleting them is safe and eliminates the crash.

## Alternative: Pin PyQt6 Version

If deleting plugins isn't an option, you can pin to PyQt6 < 6.5:

```
PyQt6>=6.4,<6.5
```

However, this may not work for all platforms (e.g., no pre-built wheels for Linux arm64).

## Troubleshooting

### "Team ID mismatch" Error

```
code signature not valid for use in process: mapping process and mapped file
(non-platform) have different Team IDs
```

**Cause:** Some binaries were signed with different identities.

**Fix:** Clear all signatures before re-signing:
```bash
find dist/YourApp.app -name "_CodeSignature" -exec rm -rf {} +
codesign --force --deep --sign - dist/YourApp.app
```

### Segfault (Exit Code 139)

**Cause:** Usually the Qt permission plugin crash.

**Fix:** Delete the `libqdarwinpermissionplugin_*.dylib` files.

### App Crashes When Run from `/tmp`

**Cause:** macOS bundle context issues when running from temporary directories.

**Fix:** This is expected behavior. Install the app to `/Applications` or `~/Applications` and use Finder or `open` command to launch.

## References

- [PyInstaller macOS Bundling](https://pyinstaller.org/en/stable/spec-files.html#spec-file-options-for-a-macos-bundle)
- [Apple Code Signing Guide](https://developer.apple.com/documentation/security/code_signing_services)
- [Qt 6.5 Permission Changes](https://doc.qt.io/qt-6/permissions.html)
- [PyInstaller Issue #7789](https://github.com/pyinstaller/pyinstaller/issues/7789) - PyQt6 macOS issues

## Credits

This documentation was developed through extensive debugging and research. Special thanks to the AI-driven research that identified the Qt permission plugin as the root cause.
