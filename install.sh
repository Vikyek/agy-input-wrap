#!/usr/bin/env bash
set -euo pipefail

# Installer for agy-input-wrap
# Links agy-input-wrap into ~/.local/bin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
TARGET="${BIN_DIR}/agy-input-wrap"
SOURCE="${SCRIPT_DIR}/bin/agy-input-wrap"

mkdir -p "${BIN_DIR}"
chmod +x "${SOURCE}"

# Create or refresh atomic symlink
ln -sf "${SOURCE}" "${TARGET}"
chmod +x "${TARGET}"

echo "✅ Installed agy-input-wrap successfully:"
echo "   Source: ${SOURCE}"
echo "   Target: ${TARGET}"
echo ""
echo "Verify installation:"
echo "   ${TARGET} --version"
echo "   ${TARGET} --list-plugins"
