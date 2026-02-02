#!/bin/bash
# PyTodo-Qt Linux Uninstallation Script
# Removes files installed by install.sh

set -e

PREFIX="${HOME}/.local"

echo "Uninstalling PyTodo-Qt from ${PREFIX}..."

# Remove launcher
if [ -f "${PREFIX}/bin/pytodo-qt" ]; then
    rm -f "${PREFIX}/bin/pytodo-qt"
    echo "  Removed ${PREFIX}/bin/pytodo-qt"
fi

# Remove application files
if [ -d "${PREFIX}/lib/pytodo-qt" ]; then
    rm -rf "${PREFIX}/lib/pytodo-qt"
    echo "  Removed ${PREFIX}/lib/pytodo-qt/"
fi

# Remove desktop file
if [ -f "${PREFIX}/share/applications/pytodo-qt.desktop" ]; then
    rm -f "${PREFIX}/share/applications/pytodo-qt.desktop"
    echo "  Removed ${PREFIX}/share/applications/pytodo-qt.desktop"
fi

# Remove icon
if [ -f "${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png" ]; then
    rm -f "${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png"
    echo "  Removed ${PREFIX}/share/icons/hicolor/256x256/apps/pytodo-qt.png"
fi

# Update icon cache if available
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "${PREFIX}/share/icons/hicolor" 2>/dev/null || true
fi

# Update desktop database if available
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "${PREFIX}/share/applications" 2>/dev/null || true
fi

echo ""
echo "PyTodo-Qt has been uninstalled."
echo ""

# Ask about user data
CONFIG_DIR="${HOME}/.config/pytodo-qt"
DATA_DIR="${HOME}/.local/share/pytodo-qt"

if [ -d "${CONFIG_DIR}" ] || [ -d "${DATA_DIR}" ]; then
    echo "User data was preserved:"
    [ -d "${CONFIG_DIR}" ] && echo "  - ${CONFIG_DIR} (configuration)"
    [ -d "${DATA_DIR}" ] && echo "  - ${DATA_DIR} (tasks database)"
    echo ""
    read -p "Do you want to remove user data as well? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        [ -d "${CONFIG_DIR}" ] && rm -rf "${CONFIG_DIR}" && echo "  Removed ${CONFIG_DIR}"
        [ -d "${DATA_DIR}" ] && rm -rf "${DATA_DIR}" && echo "  Removed ${DATA_DIR}"
        echo ""
        echo "All user data has been removed."
    else
        echo "User data has been kept."
    fi
fi
