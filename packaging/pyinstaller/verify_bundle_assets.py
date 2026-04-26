"""Verify that every git-tracked non-Python data file under src/pytodo_qt/
is present in the PyInstaller build output. Run after pyinstaller and
before packaging.

The expected set is derived from `git ls-files src/pytodo_qt/` so it
auto-tracks any new data file added under the package without spec or
verifier maintenance, while ignoring gitignored local files (Claude
settings, __pycache__, IDE artifacts, etc.).

Bundle layout differs per platform:
- Linux/Windows onedir: dist/pytodo-qt/_internal/pytodo_qt/
- macOS app bundle:     dist/pytodo-qt.app/Contents/Frameworks/pytodo_qt/

Exits 0 when every expected file is present at its corresponding bundle
path, 1 otherwise with a clear message naming the missing files.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC_PACKAGE_REL = Path("src") / "pytodo_qt"

_SKIP_SUFFIXES = {".py", ".pyc"}

# Files tracked in source but not expected at the pytodo_qt/ runtime path.
# These are build-time-only artifacts that PyInstaller relocates via spec
# parameters other than `datas`:
#   - .icns: macOS app bundle icon, placed at Contents/Resources/ via
#     BUNDLE(icon=...). Not loaded at runtime.
#   - .ico: Windows executable icon, embedded into the .exe resource
#     section via EXE(icon=...). Not loaded at runtime.
_EXCLUDED_FROM_RUNTIME = frozenset(
    {
        "gui/icons/pytodo-qt.icns",
        "gui/icons/pytodo-qt.ico",
    }
)


def _find_bundled_package(dist_root: Path) -> Path | None:
    """Locate the bundled pytodo_qt/ directory inside a PyInstaller dist tree."""
    candidates = [
        dist_root / "pytodo-qt.app" / "Contents" / "Frameworks" / "pytodo_qt",
        dist_root / "pytodo-qt" / "_internal" / "pytodo_qt",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _expected_files() -> list[Path]:
    """Return tracked non-Python data files under the source package, as relative paths."""
    result = subprocess.run(
        ["git", "ls-files", "--", str(SRC_PACKAGE_REL)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    out: list[Path] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        p = Path(line)
        if p.suffix in _SKIP_SUFFIXES:
            continue
        rel = p.relative_to(SRC_PACKAGE_REL)
        if rel.as_posix() in _EXCLUDED_FROM_RUNTIME:
            continue
        out.append(rel)
    return sorted(out)


def main() -> int:
    dist_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    if not dist_root.is_dir():
        print(f"verify-bundle: dist root not found: {dist_root}", file=sys.stderr)
        return 1

    bundled = _find_bundled_package(dist_root)
    if bundled is None:
        print(
            f"verify-bundle: could not locate bundled pytodo_qt/ under {dist_root}. "
            "Expected dist/pytodo-qt.app/Contents/Frameworks/pytodo_qt/ (macOS) or "
            "dist/pytodo-qt/_internal/pytodo_qt/ (Linux/Windows).",
            file=sys.stderr,
        )
        return 1

    expected = _expected_files()
    missing = [rel for rel in expected if not (bundled / rel).exists()]

    if missing:
        print(
            f"verify-bundle: {len(missing)} data file(s) missing from bundle ({bundled}):",
            file=sys.stderr,
        )
        for rel in missing:
            print(f"  {rel}", file=sys.stderr)
        print(
            "These files are tracked in src/pytodo_qt/ but were not collected "
            "into the bundle. Update packaging/pyinstaller/pytodo-qt.spec to "
            "include them via collect_data_files or an explicit datas entry. "
            "If a file is intentionally build-only (relocated by EXE/BUNDLE "
            "icon parameters, etc.), add its relative path to "
            "_EXCLUDED_FROM_RUNTIME at the top of this script.",
            file=sys.stderr,
        )
        return 1

    print(f"verify-bundle: ok ({len(expected)} data file(s) verified at {bundled})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
