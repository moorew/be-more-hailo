#!/bin/bash
# rollback_hailo52.sh — Undo the HailoRT 5.3 upgrade and restore 5.2.
# Generated automatically by upgrade_hailo53.sh on Fri 22 May 11:13:37 EDT 2026.
# Run from inside the be-more-agent project directory.

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SNAPSHOT_DIR="$SCRIPT_DIR/hailo52_snapshot"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/rollback_hailo52_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo ""
echo "BMO Hailo 5.2 Rollback  —  log: $LOG_FILE"
echo "════════════════════════════════════════════════════"
echo "[11:13:37] Rollback started"

if [ ! -d "$SNAPSHOT_DIR" ]; then
    echo "ERROR: Snapshot directory not found at $SNAPSHOT_DIR"
    exit 1
fi

echo ""
echo "This will:"
echo "  1. Stop BMO services"
echo "  2. Purge HailoRT 5.3 packages"
echo "  3. Reinstall HailoRT 5.2 packages from snapshot"
echo "  4. Restore hailo-ollama binary and manifests"
echo "  5. Restore core/config.py"
echo "  6. Restart services"
echo ""
read -rp "Continue? [y/N] " confirm
[[ "${confirm,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# Stop services
echo "[11:13:37] Stopping BMO services..."
sudo systemctl stop bmo-ollama.service 2>/dev/null || true
sudo systemctl stop bmo-web.service    2>/dev/null || true
sudo pkill -x hailo-ollama 2>/dev/null || true
sleep 1

# Purge 5.3 packages
echo "[11:13:37] Purging HailoRT 5.3 packages..."
sudo apt-get remove --purge -y hailort hailort-pcie-driver hailo-gen-ai-model-zoo 2>/dev/null || true
for pkg in hailort hailort-pcie-driver hailo-gen-ai-model-zoo; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        sudo dpkg --force-all --purge "$pkg" 2>/dev/null || true
    fi
done
echo "[11:13:37] 5.3 packages removed"

# Reinstall 5.2 from snapshot
echo "[11:13:37] Reinstalling HailoRT 5.2 from snapshot..."
for deb in "$SNAPSHOT_DIR"/*.deb; do
    [ -f "$deb" ] || continue
    echo "  Installing: $(basename "$deb")"
    sudo dpkg -i "$deb" 2>&1 | sed 's/^/    /' || {
        echo "  WARNING: dpkg -i $(basename "$deb") returned non-zero, trying --force-overwrite"
        sudo dpkg --force-overwrite -i "$deb" 2>&1 | sed 's/^/    /' || true
    }
done
sudo apt-get install -f -y 2>/dev/null || true

# Restore hailo-ollama binary
if [ -f "$SNAPSHOT_DIR/hailo-ollama.bin" ]; then
    echo "[11:13:37] Restoring hailo-ollama binary..."
    sudo cp "$SNAPSHOT_DIR/hailo-ollama.bin" /usr/bin/hailo-ollama
    sudo chmod +x /usr/bin/hailo-ollama
    echo "  Restored to /usr/bin/hailo-ollama"
fi

# Restore manifests
if [ -d "$SNAPSHOT_DIR/hailo-ollama-models" ]; then
    echo "[11:13:37] Restoring hailo-ollama manifests..."
    mkdir -p "$HOME/.local/share/hailo-ollama"
    cp -r "$SNAPSHOT_DIR/hailo-ollama-models" "$HOME/.local/share/hailo-ollama/models"
    echo "  Manifests restored"
fi

# Restore config.py
echo "[11:13:37] Restoring core/config.py..."
cp "$SNAPSHOT_DIR/config.py.bak" "$SCRIPT_DIR/core/config.py"
echo "  config.py restored"

# Reload kernel module
echo "[11:13:37] Reloading kernel module..."
sudo rmmod hailo1x_pci 2>/dev/null || true
sudo modprobe hailo1x_pci 2>/dev/null && echo "  hailo1x_pci loaded" || {
    echo "  WARNING: modprobe failed — a reboot may be required"
}
ls -la /dev/hailo* 2>/dev/null || echo "  /dev/hailo0 not found (reboot may be needed)"

# Restart services
echo "[11:13:37] Restarting services..."
sudo systemctl start bmo-ollama.service 2>/dev/null || true
sudo systemctl start bmo-web.service    2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════"
echo "Rollback to HailoRT 5.2 complete."
echo "Full log: $LOG_FILE"
echo "If /dev/hailo0 is missing, run: sudo reboot"
