#!/bin/bash
# PyTodo-Qt Linux Installation Script
# Installs to user's home directory (~/.local/)
# No root required. Ensure ~/.local/bin is in your PATH.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HOME}/.local"

echo "Installing PyTodo-Qt to ${PREFIX}..."

# Create directories
mkdir -p "${PREFIX}/bin"
mkdir -p "${PREFIX}/lib/pytodo-qt"
mkdir -p "${PREFIX}/share/applications"
mkdir -p "${PREFIX}/share/icons/hicolor/256x256/apps"

# Install application files (onedir mode - multiple files)
cp -r "${SCRIPT_DIR}"/* "${PREFIX}/lib/pytodo-qt/"
# Remove non-application files from lib directory
rm -f "${PREFIX}/lib/pytodo-qt/pytodo-qt.desktop"
rm -f "${PREFIX}/lib/pytodo-qt/install.sh"
rm -f "${PREFIX}/lib/pytodo-qt/pytodo-qt.png"
echo "  Installed application to ${PREFIX}/lib/pytodo-qt/"

# Create launcher script in bin
cat > "${PREFIX}/bin/pytodo-qt" << 'LAUNCHER'
#!/bin/bash
exec ~/.local/lib/pytodo-qt/pytodo-qt "$@"
LAUNCHER
chmod 755 "${PREFIX}/bin/pytodo-qt"
echo "  Installed launcher to ${PREFIX}/bin/pytodo-qt"

# Install icon first
install -m 644 "${SCRIPT_DIR}/pytodo-qt.png" "${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png"
echo "  Installed icon to ${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png"

# Install desktop file with absolute icon path for reliability
sed "s|Icon=pytodo-qt|Icon=${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png|" \
    "${SCRIPT_DIR}/pytodo-qt.desktop" > "${PREFIX}/share/applications/pytodo-qt.desktop"
chmod 644 "${PREFIX}/share/applications/pytodo-qt.desktop"
echo "  Installed desktop file to ${PREFIX}/share/applications/pytodo-qt.desktop"

# Update icon cache if available
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "${PREFIX}/share/icons/hicolor" 2>/dev/null || true
fi

# Update desktop database if available
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "${PREFIX}/share/applications" 2>/dev/null || true
fi

echo ""
echo "Installation complete!"
echo ""
echo "Make sure ${PREFIX}/bin is in your PATH:"
echo "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
echo ""
echo "You can now run 'pytodo-qt' from the command line or find it in your application menu."
