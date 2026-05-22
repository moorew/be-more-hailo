#!/bin/bash
# upgrade_hailo53.sh — Upgrade HailoRT 5.2 (Pi repo) → 5.3 (upstream vendor)
# and pull Qwen3-1.7B / Qwen3-VL-2B model assets.
#
# Includes:
#   • Full timestamped log capture
#   • Pre-upgrade snapshot of every installed Hailo package (dpkg-repack)
#   • Auto-generated rollback_hailo52.sh to undo everything
#
# Run from inside the be-more-agent project directory.

set -uo pipefail   # -e omitted intentionally — we handle errors explicitly

# ─── Logging setup ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/upgrade_hailo53_${TIMESTAMP}.log"

# Tee all stdout+stderr to the log file, preserving colours in terminal
exec > >(tee -a "$LOG_FILE") 2>&1

log_ts() { echo "[$(date '+%H:%M:%S')] $*"; }

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()   { log_ts "$(echo -e "${GREEN}[OK]${NC}   $*")"; }
info()  { log_ts "$(echo -e "${CYAN}[INFO]${NC} $*")"; }
warn()  { log_ts "$(echo -e "${YELLOW}[WARN]${NC} $*")"; }
die()   { log_ts "$(echo -e "${RED}[FAIL]${NC} $*")"; echo ""; echo "Full log: $LOG_FILE"; exit 1; }
step()  { echo ""; log_ts "$(echo -e "${BOLD}${CYAN}══ $* ══${NC}")"; }
diag()  { log_ts "$(echo -e "  ${YELLOW}▷${NC} $*")"; }

echo ""
echo -e "${BOLD}BMO Hailo 5.3 Upgrade${NC}  —  log: $LOG_FILE"
echo "════════════════════════════════════════════════════"
log_ts "Script started at $(date)"

# ─── Config ───────────────────────────────────────────────────────────────────

HAILO_VER="5.3.0"
HAILO_BASE_URL="https://dev-public.hailo.ai/2026_04/Hailo10"
MODEL_CDN="https://dev-public.hailo.ai/v${HAILO_VER}/blob"
SNAPSHOT_DIR="$SCRIPT_DIR/hailo52_snapshot"
CONFIG_FILE="$SCRIPT_DIR/core/config.py"

# ─── Helper: run with logging ─────────────────────────────────────────────────

# Run a command; log each line with timestamp prefix; return its exit code
run_logged() {
    local label="$1"; shift
    diag "Running: $*"
    local rc=0
    "$@" 2>&1 | while IFS= read -r line; do
        log_ts "    [$label] $line"
    done || rc=${PIPESTATUS[0]}
    return $rc
}

# Run a command; capture output to a variable; log it; return exit code
capture_logged() {
    local label="$1" var="$2"; shift 2
    diag "Running: $*"
    local out rc=0
    out=$("$@" 2>&1) || rc=$?
    while IFS= read -r line; do
        log_ts "    [$label] $line"
    done <<< "$out"
    printf -v "$var" '%s' "$out"
    return $rc
}

# ─── Diagnostic snapshot helper ───────────────────────────────────────────────

dump_system_state() {
    local label="$1"
    info "System state snapshot: $label"
    diag "--- dpkg hailo packages ---"
    dpkg -l '*hailo*' '*hailort*' 2>/dev/null | grep -v "^|" | while IFS= read -r l; do log_ts "  $l"; done || true
    diag "--- lsmod hailo ---"
    lsmod | grep -i hailo | while IFS= read -r l; do log_ts "  $l"; done || true
    diag "--- /dev/hailo* ---"
    ls -la /dev/hailo* 2>/dev/null | while IFS= read -r l; do log_ts "  $l"; done || true
    diag "--- hailo-ollama ---"
    # NOTE: hailo-ollama has no --version flag; it starts a blocking server instead.
    if command -v hailo-ollama &>/dev/null; then
        log_ts "  hailo-ollama: $(command -v hailo-ollama)  size: $(du -h "$(command -v hailo-ollama)" | cut -f1)"
    else
        log_ts "  hailo-ollama not in PATH"
    fi
    diag "--- python3 hailo_platform ---"
    python3 -c "import hailo_platform; print('hailo_platform OK:', hailo_platform.__file__)" 2>&1 | while IFS= read -r l; do log_ts "  $l"; done || true
    diag "--- dmesg (last 5 hailo lines) ---"
    dmesg 2>/dev/null | grep -i hailo | tail -5 | while IFS= read -r l; do log_ts "  $l"; done || true
}

# ═══════════════════════════════════════════════════════════════════════════════
step "PRE-FLIGHT"
# ═══════════════════════════════════════════════════════════════════════════════

info "Detecting current HailoRT version..."
CURRENT_VER=$(dpkg-query -W -f='${Version}' h10-hailort 2>/dev/null \
              || dpkg-query -W -f='${Version}' hailort 2>/dev/null \
              || echo "unknown")
info "Installed: ${CURRENT_VER}  →  Target: ${HAILO_VER}"

if [[ "$CURRENT_VER" == "$HAILO_VER" ]]; then
    warn "HailoRT ${HAILO_VER} is already installed."
    dump_system_state "already-at-target"
    exit 0
fi

if [[ "$CURRENT_VER" == "unknown" ]]; then
    die "No Hailo runtime detected. Run install.sh first."
fi

dump_system_state "before-upgrade"

echo ""
info "This will:"
info "  1. Snapshot every installed Hailo package → $SNAPSHOT_DIR/"
info "  2. Auto-generate rollback_hailo52.sh (one command to undo everything)"
info "  3. Purge the Pi-repo 5.2 packages"
info "  4. Install upstream 5.3 packages"
info "  5. Pull Qwen3-1.7B-Instruct LLM, download Qwen3-VL-2B / Whisper-Small HEFs"
info "  6. Patch core/config.py with the new model names"
echo ""
read -rp "Continue? [y/N] " confirm
[[ "${confirm,,}" == "y" ]] || { warn "Aborted."; exit 0; }

# ═══════════════════════════════════════════════════════════════════════════════
step "SNAPSHOT  (rollback safety net)"
# ═══════════════════════════════════════════════════════════════════════════════

info "Installing dpkg-repack if needed..."
sudo apt-get install -y dpkg-repack 2>&1 | grep -v "^Get\|^Fetch\|^Inst\|^Conf\|^Reading\|^Building" | \
    while IFS= read -r l; do log_ts "  [apt] $l"; done || warn "dpkg-repack install returned non-zero (may already be installed)"

mkdir -p "$SNAPSHOT_DIR"
info "Repacking installed Hailo packages into $SNAPSHOT_DIR/ ..."

for pkg in h10-hailort python3-h10-hailort h10-hailort-pcie-driver hailo-h10-all hailo-gen-ai-model-zoo; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        diag "Repacking $pkg ..."
        (cd "$SNAPSHOT_DIR" && sudo dpkg-repack "$pkg" 2>&1 | while IFS= read -r l; do log_ts "  [dpkg-repack] $l"; done) \
            && log "  $pkg → $(ls "$SNAPSHOT_DIR/${pkg}"*.deb 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo '?')" \
            || warn "  Failed to repack $pkg (may not matter if it's a meta-package with no files)"
    else
        info "  $pkg not installed, skipping repack"
    fi
done

info "Saving hailo-ollama binary..."
if command -v hailo-ollama &>/dev/null; then
    OLLAMA_BIN=$(command -v hailo-ollama)
    cp "$OLLAMA_BIN" "$SNAPSHOT_DIR/hailo-ollama.bin"
    log "  hailo-ollama saved ($(du -h "$SNAPSHOT_DIR/hailo-ollama.bin" | cut -f1))"
else
    warn "  hailo-ollama not found in PATH — skipping binary save"
fi

info "Saving hailo-ollama model manifests..."
MANIFESTS_SRC="$HOME/.local/share/hailo-ollama/models"
if [ -d "$MANIFESTS_SRC" ]; then
    cp -r "$MANIFESTS_SRC" "$SNAPSHOT_DIR/hailo-ollama-models"
    log "  manifests saved ($(find "$SNAPSHOT_DIR/hailo-ollama-models" -name "manifest.json" | wc -l) manifests)"
else
    warn "  $MANIFESTS_SRC not found — no manifest backup"
fi

info "Saving core/config.py..."
cp "$CONFIG_FILE" "$SNAPSHOT_DIR/config.py.bak"
log "  config.py saved"

info "Saving current LLM manifest checksums..."
dpkg-query -W -f='${Package}\t${Version}\n' 2>/dev/null | grep -i hailo > "$SNAPSHOT_DIR/dpkg_state.txt" || true
lsmod > "$SNAPSHOT_DIR/lsmod_before.txt" 2>/dev/null || true
log "  dpkg state and lsmod saved"

# ── Generate rollback script ──────────────────────────────────────────────────

info "Generating rollback_hailo52.sh ..."
cat > "$SCRIPT_DIR/rollback_hailo52.sh" << ROLLBACK_EOF
#!/bin/bash
# rollback_hailo52.sh — Undo the HailoRT 5.3 upgrade and restore 5.2.
# Generated automatically by upgrade_hailo53.sh on $(date).
# Run from inside the be-more-agent project directory.

set -uo pipefail
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
SNAPSHOT_DIR="\$SCRIPT_DIR/hailo52_snapshot"
LOG_DIR="\$SCRIPT_DIR/logs"
mkdir -p "\$LOG_DIR"
LOG_FILE="\$LOG_DIR/rollback_hailo52_\$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "\$LOG_FILE") 2>&1

echo ""
echo "BMO Hailo 5.2 Rollback  —  log: \$LOG_FILE"
echo "════════════════════════════════════════════════════"
echo "[$(date '+%H:%M:%S')] Rollback started"

if [ ! -d "\$SNAPSHOT_DIR" ]; then
    echo "ERROR: Snapshot directory not found at \$SNAPSHOT_DIR"
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
[[ "\${confirm,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# Stop services
echo "[$(date '+%H:%M:%S')] Stopping BMO services..."
sudo systemctl stop bmo-ollama.service 2>/dev/null || true
sudo systemctl stop bmo-web.service    2>/dev/null || true
sudo pkill -x hailo-ollama 2>/dev/null || true
sleep 1

# Purge 5.3 packages
echo "[$(date '+%H:%M:%S')] Purging HailoRT 5.3 packages..."
sudo apt-get remove --purge -y hailort hailort-pcie-driver hailo-gen-ai-model-zoo 2>/dev/null || true
for pkg in hailort hailort-pcie-driver hailo-gen-ai-model-zoo; do
    if dpkg -l "\$pkg" 2>/dev/null | grep -q "^ii"; then
        sudo dpkg --force-all --purge "\$pkg" 2>/dev/null || true
    fi
done
echo "[$(date '+%H:%M:%S')] 5.3 packages removed"

# Reinstall 5.2 from snapshot
echo "[$(date '+%H:%M:%S')] Reinstalling HailoRT 5.2 from snapshot..."
for deb in "\$SNAPSHOT_DIR"/*.deb; do
    [ -f "\$deb" ] || continue
    echo "  Installing: \$(basename "\$deb")"
    sudo dpkg -i "\$deb" 2>&1 | sed 's/^/    /' || {
        echo "  WARNING: dpkg -i \$(basename "\$deb") returned non-zero, trying --force-overwrite"
        sudo dpkg --force-overwrite -i "\$deb" 2>&1 | sed 's/^/    /' || true
    }
done
sudo apt-get install -f -y 2>/dev/null || true

# Restore hailo-ollama binary
if [ -f "\$SNAPSHOT_DIR/hailo-ollama.bin" ]; then
    echo "[$(date '+%H:%M:%S')] Restoring hailo-ollama binary..."
    sudo cp "\$SNAPSHOT_DIR/hailo-ollama.bin" /usr/bin/hailo-ollama
    sudo chmod +x /usr/bin/hailo-ollama
    echo "  Restored to /usr/bin/hailo-ollama"
fi

# Restore manifests
if [ -d "\$SNAPSHOT_DIR/hailo-ollama-models" ]; then
    echo "[$(date '+%H:%M:%S')] Restoring hailo-ollama manifests..."
    mkdir -p "\$HOME/.local/share/hailo-ollama"
    cp -r "\$SNAPSHOT_DIR/hailo-ollama-models" "\$HOME/.local/share/hailo-ollama/models"
    echo "  Manifests restored"
fi

# Restore config.py
echo "[$(date '+%H:%M:%S')] Restoring core/config.py..."
cp "\$SNAPSHOT_DIR/config.py.bak" "\$SCRIPT_DIR/core/config.py"
echo "  config.py restored"

# Reload kernel module
echo "[$(date '+%H:%M:%S')] Reloading kernel module..."
sudo rmmod hailo1x_pci 2>/dev/null || true
sudo modprobe hailo1x_pci 2>/dev/null && echo "  hailo1x_pci loaded" || {
    echo "  WARNING: modprobe failed — a reboot may be required"
}
ls -la /dev/hailo* 2>/dev/null || echo "  /dev/hailo0 not found (reboot may be needed)"

# Restart services
echo "[$(date '+%H:%M:%S')] Restarting services..."
sudo systemctl start bmo-ollama.service 2>/dev/null || true
sudo systemctl start bmo-web.service    2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════"
echo "Rollback to HailoRT 5.2 complete."
echo "Full log: \$LOG_FILE"
echo "If /dev/hailo0 is missing, run: sudo reboot"
ROLLBACK_EOF

chmod +x "$SCRIPT_DIR/rollback_hailo52.sh"
log "rollback_hailo52.sh generated — run it any time to undo this upgrade"

# ═══════════════════════════════════════════════════════════════════════════════
step "DOWNLOAD 5.3 PACKAGES"
# ═══════════════════════════════════════════════════════════════════════════════

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
info "Temporary directory: $TMP_DIR"

PKG_URLS=(
    "$HAILO_BASE_URL/hailort_${HAILO_VER}_arm64.deb"
    "$HAILO_BASE_URL/hailort-pcie-driver_${HAILO_VER}_all.deb"
    "$HAILO_BASE_URL/hailo_gen_ai_model_zoo_${HAILO_VER}_arm64.deb"
)

for url in "${PKG_URLS[@]}"; do
    fname=$(basename "$url")
    info "Downloading $fname ..."
    wget -q --show-progress -O "${TMP_DIR}/${fname}" "$url" 2>&1 | \
        while IFS= read -r l; do log_ts "  [wget] $l"; done
    SIZE=$(stat --printf="%s" "${TMP_DIR}/${fname}" 2>/dev/null || echo 0)
    if [ "${SIZE}" -lt 10000 ]; then
        die "Download of $fname looks incomplete (${SIZE} bytes)"
    fi
    log "  $fname  ($(du -h "${TMP_DIR}/${fname}" | cut -f1))"
done

# Inspect what the packages actually install
info "Inspecting package contents..."
for deb in "${TMP_DIR}"/*.deb; do
    fname=$(basename "$deb")
    diag "Contents of $fname:"
    dpkg-deb --contents "$deb" 2>/dev/null | \
        grep -v "^d" | awk '{print $NF}' | head -20 | \
        while IFS= read -r l; do log_ts "      $l"; done
done

# ═══════════════════════════════════════════════════════════════════════════════
step "STOP SERVICES"
# ═══════════════════════════════════════════════════════════════════════════════

info "Stopping BMO services..."
sudo systemctl stop bmo-ollama.service 2>&1 | while IFS= read -r l; do log_ts "  [systemctl] $l"; done || true
sudo systemctl stop bmo-web.service    2>&1 | while IFS= read -r l; do log_ts "  [systemctl] $l"; done || true
sudo pkill -x hailo-ollama 2>/dev/null && info "  Killed hailo-ollama process" || true
sleep 1

info "Unloading hailo1x_pci kernel module..."
if lsmod | grep -q hailo1x_pci; then
    sudo rmmod hailo1x_pci 2>&1 | while IFS= read -r l; do log_ts "  [rmmod] $l"; done \
        && log "  hailo1x_pci unloaded" \
        || warn "  rmmod returned non-zero (module may still be in use)"
else
    info "  hailo1x_pci was not loaded"
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "PURGE Pi-REPO 5.2 PACKAGES"
# ═══════════════════════════════════════════════════════════════════════════════

info "Removing Pi-repo Hailo packages via apt..."
sudo apt-get remove --purge -y \
    hailo-h10-all \
    python3-h10-hailort \
    hailo-gen-ai-model-zoo \
    2>&1 | while IFS= read -r l; do log_ts "  [apt] $l"; done || \
    warn "apt remove returned non-zero (some packages may not have been apt-managed)"

# Force-purge runtime and driver if apt left them (installed from dpkg directly)
for pkg in h10-hailort-pcie-driver h10-hailort; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        warn "  $pkg still installed after apt remove — force-purging with dpkg"
        sudo dpkg --force-all --purge "$pkg" 2>&1 | \
            while IFS= read -r l; do log_ts "  [dpkg-purge] $l"; done || true
    else
        log "  $pkg not present (already removed)"
    fi
done

info "Verifying purge..."
REMAINING=$(dpkg -l '*h10-hailo*' '*hailort*' '*hailo-h10*' '*hailo-gen*' 2>/dev/null | grep "^ii" || true)
if [ -n "$REMAINING" ]; then
    warn "Some packages remain after purge:"
    echo "$REMAINING" | while IFS= read -r l; do log_ts "  $l"; done
else
    log "All Pi-repo Hailo packages removed"
fi

dump_system_state "after-purge"

# ═══════════════════════════════════════════════════════════════════════════════
step "INSTALL UPSTREAM 5.3 PACKAGES"
# ═══════════════════════════════════════════════════════════════════════════════

# Runtime library first — everything else depends on it
info "Installing hailort_${HAILO_VER}_arm64.deb (runtime library)..."
sudo dpkg -i "${TMP_DIR}/hailort_${HAILO_VER}_arm64.deb" 2>&1 | \
    while IFS= read -r l; do log_ts "  [dpkg] $l"; done
RC=${PIPESTATUS[0]}
[ "$RC" -ne 0 ] && die "hailort runtime install failed (exit $RC)"
log "  hailort runtime installed"

# PCIe driver — DKMS builds the kernel module against the running kernel
info "Installing hailort-pcie-driver_${HAILO_VER}_all.deb (DKMS driver)..."
info "  This builds the kernel module — may take 1-2 minutes..."
sudo dpkg -i "${TMP_DIR}/hailort-pcie-driver_${HAILO_VER}_all.deb" 2>&1 | \
    while IFS= read -r l; do log_ts "  [dpkg/dkms] $l"; done
RC=${PIPESTATUS[0]}
[ "$RC" -ne 0 ] && warn "PCIe driver install returned non-zero (exit $RC) — checking DKMS status..."

# Inspect DKMS build result
info "DKMS status after driver install:"
dkms status 2>&1 | while IFS= read -r l; do log_ts "  [dkms] $l"; done || true

# Model zoo (hailo-ollama binary + Qwen3 model manifests)
info "Installing hailo_gen_ai_model_zoo_${HAILO_VER}_arm64.deb (hailo-ollama + manifests)..."
sudo dpkg -i "${TMP_DIR}/hailo_gen_ai_model_zoo_${HAILO_VER}_arm64.deb" 2>&1 | \
    while IFS= read -r l; do log_ts "  [dpkg] $l"; done
RC=${PIPESTATUS[0]}
[ "$RC" -ne 0 ] && warn "model zoo install returned non-zero (exit $RC)"

# Satisfy any newly declared dependencies
info "Resolving any new dependencies..."
sudo apt-get install -f -y 2>&1 | while IFS= read -r l; do log_ts "  [apt-fix] $l"; done || true

dump_system_state "after-install"

# ═══════════════════════════════════════════════════════════════════════════════
step "LOAD 5.3 KERNEL MODULE"
# ═══════════════════════════════════════════════════════════════════════════════

info "Loading hailo1x_pci with new 5.3 driver..."
sudo modprobe hailo1x_pci 2>&1 | while IFS= read -r l; do log_ts "  [modprobe] $l"; done
RC=${PIPESTATUS[0]}

if [ "$RC" -ne 0 ]; then
    warn "modprobe returned non-zero — checking dmesg for details..."
    dmesg | tail -20 | while IFS= read -r l; do log_ts "  [dmesg] $l"; done
    warn "A reboot may be required to load the new kernel module."
    warn "After reboot, run: hailortcli fw-control identify"
else
    log "hailo1x_pci loaded"
    sleep 1
    # HailoRT 5.3 renames the device from /dev/hailo0 to /dev/h1x-0.
    # Create a udev rule to symlink it back for backward compatibility.
    UDEV_RULE='/etc/udev/rules.d/99-hailo-compat.rules'
    if [ ! -f "$UDEV_RULE" ]; then
        info "Creating udev symlink rule $UDEV_RULE ..."
        echo 'KERNEL=="h1x-[0-9]*", SUBSYSTEM=="hailo1x", SYMLINK+="hailo%n"' | \
            sudo tee "$UDEV_RULE" > /dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        sleep 1
        log "  udev rule installed; /dev/hailo0 should now symlink to /dev/h1x-0"
    else
        info "  udev compat rule already present"
    fi

    if [ -e /dev/hailo0 ] || [ -e /dev/h1x-0 ]; then
        log "/dev/hailo* device is available ($(ls /dev/hailo* /dev/h1x-* 2>/dev/null | tr '\n' ' '))"
        info "Firmware version:"
        hailortcli fw-control identify 2>&1 | while IFS= read -r l; do log_ts "  [fw] $l"; done || \
            warn "  fw-control failed — firmware flash may happen on first reboot"
    else
        warn "/dev/hailo0 and /dev/h1x-0 not found — dmesg output:"
        dmesg | grep -i hailo | tail -15 | while IFS= read -r l; do log_ts "  [dmesg] $l"; done || true
        warn "A reboot is likely needed for the 5.3 firmware to flash and the device to appear."
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "INSTALL Python BINDINGS (pip wheel)"
# ═══════════════════════════════════════════════════════════════════════════════

# HailoRT 5.3 ships Python bindings as a pip wheel, NOT a .deb.
# The h10-hailort 5.2 deb linked pyhailort against libhailort.so.5.2.0, so the
# purge above removed the old Python module.  The new 5.3 wheel must be
# installed explicitly.  File must keep the full platform tag in its filename —
# renaming to a plain .whl breaks pip's wheel-compatibility check.
PY_WHEEL_URL="${HAILO_BASE_URL}/hailort-${HAILO_VER}-cp313-cp313-linux_aarch64.whl"
PY_WHEEL_FILE="/tmp/hailort-${HAILO_VER}-cp313-cp313-linux_aarch64.whl"
info "Downloading hailort Python wheel..."
wget -q --show-progress -O "$PY_WHEEL_FILE" "$PY_WHEEL_URL" 2>&1 | \
    while IFS= read -r l; do log_ts "  [wget] $l"; done
if [ -f "$PY_WHEEL_FILE" ] && [ "$(stat --printf='%s' "$PY_WHEEL_FILE")" -gt 1000000 ]; then
    log "  Wheel downloaded ($(du -h "$PY_WHEEL_FILE" | cut -f1))"
else
    die "hailort Python wheel download failed or too small — cannot continue without Python bindings"
fi

info "Installing hailort wheel system-wide..."
sudo pip install --break-system-packages "$PY_WHEEL_FILE" 2>&1 | \
    while IFS= read -r l; do log_ts "  [pip] $l"; done \
  && log "  hailort wheel installed" \
  || die "pip install of hailort wheel failed"

# ═══════════════════════════════════════════════════════════════════════════════
step "VERIFY Python API"
# ═══════════════════════════════════════════════════════════════════════════════

info "Testing hailo_platform import..."
python3 -c "
import hailo_platform
print('hailo_platform path:', hailo_platform.__file__)
from hailo_platform.genai import LLM, VLM, Speech2Text
print('LLM, VLM, Speech2Text all importable')
" 2>&1 | while IFS= read -r l; do log_ts "  [python] $l"; done \
  && log "hailo_platform Python API OK" \
  || warn "hailo_platform import failed — check pip install output above"

# Check inside the venv too
info "Testing hailo_platform inside project venv..."
"$SCRIPT_DIR/venv/bin/python3" -c "
from hailo_platform.genai import Speech2Text, VLM
print('venv: Speech2Text, VLM importable')
" 2>&1 | while IFS= read -r l; do log_ts "  [venv-python] $l"; done \
  && log "venv hailo_platform OK" \
  || warn "hailo_platform not accessible from venv (system site-packages may need re-enabling)"

# ═══════════════════════════════════════════════════════════════════════════════
step "START hailo-ollama + PULL Qwen3"
# ═══════════════════════════════════════════════════════════════════════════════

info "hailo-ollama binary: $(command -v hailo-ollama 2>/dev/null || echo 'not found')"
# NOTE: hailo-ollama has no --version flag — it starts a blocking server.

# Copy Qwen3 manifests from the system install location to the user data dir.
# 5.3 installs manifests to /usr/share/hailo-ollama/ but the server reads from
# ~/.local/share/hailo-ollama/ — without this copy, model pulls fail.
SYSTEM_MANIFESTS="/usr/share/hailo-ollama/models/manifests"
USER_MANIFESTS="$HOME/.local/share/hailo-ollama/models/manifests"
if [ -d "$SYSTEM_MANIFESTS" ]; then
    info "Copying new model manifests to user data dir..."
    mkdir -p "$USER_MANIFESTS"
    # Copy only missing manifests (don't overwrite existing user-pulled models)
    for model_dir in "$SYSTEM_MANIFESTS"/*/; do
        model=$(basename "$model_dir")
        if [ ! -d "$USER_MANIFESTS/$model" ]; then
            cp -r "$model_dir" "$USER_MANIFESTS/$model"
            log "  Copied manifest: $model"
        else
            info "  Manifest already present: $model"
        fi
    done
else
    warn "System manifests not found at $SYSTEM_MANIFESTS — skipping copy"
fi

info "Starting hailo-ollama server for model pull..."
export OLLAMA_HOST=0.0.0.0:8000
nohup hailo-ollama serve > "$LOG_DIR/hailo-ollama_${TIMESTAMP}.log" 2>&1 &
OLLAMA_PID=$!
info "  hailo-ollama PID: $OLLAMA_PID  —  log: $LOG_DIR/hailo-ollama_${TIMESTAMP}.log"

info "Waiting for hailo-ollama to become ready (up to 60s)..."
READY=0
for i in $(seq 1 30); do
    sleep 2
    if curl -sf http://localhost:8000/api/tags > /dev/null 2>&1; then
        READY=1
        log "  hailo-ollama responded after $((i*2))s"
        break
    fi
    # Log any output from hailo-ollama while we wait
    TAIL_OUT=$(tail -3 "$LOG_DIR/hailo-ollama_${TIMESTAMP}.log" 2>/dev/null || true)
    if [ -n "$TAIL_OUT" ]; then
        echo "$TAIL_OUT" | while IFS= read -r l; do log_ts "  [ollama-init] $l"; done
    fi
    info "  Waiting... (${i}/30)"
done

if [ "$READY" -eq 0 ]; then
    warn "hailo-ollama did not respond within 60s"
    info "Last 20 lines of hailo-ollama log:"
    tail -20 "$LOG_DIR/hailo-ollama_${TIMESTAMP}.log" 2>/dev/null | \
        while IFS= read -r l; do log_ts "  [ollama-log] $l"; done
    die "hailo-ollama failed to start. See log above and $LOG_DIR/hailo-ollama_${TIMESTAMP}.log"
fi

info "Available models before pull:"
curl -sf http://localhost:8000/api/tags 2>/dev/null | \
    python3 -c "import sys,json; [print('  ', m['name']) for m in json.load(sys.stdin).get('models',[])]" 2>/dev/null || true

info "Pulling qwen3:1.7b (may take a few minutes)..."
PULL_RESULT=$(curl -sf http://localhost:8000/api/pull \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen3:1.7b","stream":false}' 2>&1) || PULL_RESULT="curl-failed"

log_ts "  [pull-result] $PULL_RESULT"
echo "$PULL_RESULT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('status') == 'success':
        print('[$(date +%H:%M:%S')]   qwen3:1.7b pulled successfully')
    else:
        print(f'[$(date +%H:%M:%S')]   WARNING unexpected response: {d}')
except Exception as e:
    print(f'[$(date +%H:%M:%S')]   WARNING could not parse pull response: {e}')
" 2>/dev/null | while IFS= read -r l; do echo "$l"; done

info "Models available after pull:"
curl -sf http://localhost:8000/api/tags 2>/dev/null | \
    python3 -c "import sys,json; [print('  ', m['name']) for m in json.load(sys.stdin).get('models',[])]" 2>/dev/null || true

kill "$OLLAMA_PID" 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════════════
step "DOWNLOAD MODEL HEFs"
# ═══════════════════════════════════════════════════════════════════════════════

cd "$SCRIPT_DIR"

download_hef() {
    local name="$1" dest="models/${1}.hef"
    if [ -f "$dest" ]; then
        log "  $dest already present ($(du -h "$dest" | cut -f1))"
        return 0
    fi
    info "  Downloading $dest ..."
    wget -c --tries=3 --show-progress -O "$dest" "${MODEL_CDN}/${name}.hef" 2>&1 | \
        while IFS= read -r l; do log_ts "  [wget] $l"; done
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ] || [ ! -f "$dest" ]; then
        warn "  Download of $name.hef failed"
        rm -f "$dest"
        return 1
    fi
    SIZE=$(stat --printf="%s" "$dest" 2>/dev/null || echo 0)
    if [ "${SIZE}" -lt 1000000 ]; then
        warn "  $dest looks incomplete (${SIZE} bytes) — removing"
        rm -f "$dest"
        return 1
    fi
    log "  $dest downloaded ($(du -h "$dest" | cut -f1))"
    return 0
}

VLM3_OK=0
download_hef "Qwen3-VL-2B-Instruct" && VLM3_OK=1

WHISPER_OK=0
download_hef "Whisper-Small" && WHISPER_OK=1

# ═══════════════════════════════════════════════════════════════════════════════
step "PATCH core/config.py"
# ═══════════════════════════════════════════════════════════════════════════════

info "Patching LLM model names (qwen2.5-instruct:1.5b → qwen3:1.7b)..."
# Use Python for safe in-place replacement — avoids sed escaping issues
python3 - "$CONFIG_FILE" << 'PYEOF'
import sys, re
path = sys.argv[1]
with open(path) as f:
    src = f.read()
src = re.sub(r'(LLM_MODEL\s*=\s*)"qwen2\.5-instruct:1\.5b"', r'\1"qwen3:1.7b"', src)
src = re.sub(r'(FAST_LLM_MODEL\s*=\s*)"qwen2\.5-instruct:1\.5b"', r'\1"qwen3:1.7b"', src)
with open(path, 'w') as f:
    f.write(src)
print("LLM_MODEL and FAST_LLM_MODEL updated to qwen3:1.7b")
PYEOF

if [ "$VLM3_OK" -eq 1 ]; then
    info "Patching VLM HEF path (Qwen2 → Qwen3)..."
    python3 - "$CONFIG_FILE" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()
src = src.replace("Qwen2-VL-2B-Instruct.hef", "Qwen3-VL-2B-Instruct.hef")
with open(path, 'w') as f:
    f.write(src)
print("VLM_HEF_PATH updated to Qwen3-VL-2B-Instruct.hef")
PYEOF
    log "  VLM path updated to Qwen3-VL-2B-Instruct.hef"
else
    warn "Qwen3-VL HEF not downloaded — keeping Qwen2-VL path in config"
fi

info "Verifying config.py diff from backup..."
diff "$SNAPSHOT_DIR/config.py.bak" "$CONFIG_FILE" | \
    while IFS= read -r l; do log_ts "  [diff] $l"; done || true

# ═══════════════════════════════════════════════════════════════════════════════
step "RESTART SERVICES"
# ═══════════════════════════════════════════════════════════════════════════════

info "Restarting BMO services..."
sudo systemctl start bmo-ollama.service 2>&1 | while IFS= read -r l; do log_ts "  [systemctl] $l"; done || \
    warn "bmo-ollama service start returned non-zero (may not be installed — use setup_services.sh)"
sudo systemctl start bmo-web.service 2>&1 | while IFS= read -r l; do log_ts "  [systemctl] $l"; done || \
    warn "bmo-web service start returned non-zero"

dump_system_state "after-upgrade"

# ═══════════════════════════════════════════════════════════════════════════════
step "SUMMARY"
# ═══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  HailoRT ${HAILO_VER} upgrade complete!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  LLM:  qwen3:1.7b       (via hailo-ollama, port 8000)"
echo "  VLM:  $([ "$VLM3_OK" -eq 1 ] && echo "Qwen3-VL-2B-Instruct.hef" || echo "Qwen2-VL-2B-Instruct.hef (Qwen3 download failed)")"
echo "  STT:  Whisper-Small.hef         ($([ "$WHISPER_OK" -eq 1 ] && echo "NPU" || echo "CPU fallback — HEF download failed"))"
echo ""
echo -e "  Snapshot: ${YELLOW}$SNAPSHOT_DIR/${NC}"
echo -e "  Rollback: ${YELLOW}./rollback_hailo52.sh${NC}"
echo -e "  Log:      ${YELLOW}$LOG_FILE${NC}"
echo ""
echo "Verify firmware:  hailortcli fw-control identify"
echo "Monitor LLM:      sudo systemctl status bmo-ollama"
echo ""
if ! [ -e /dev/hailo0 ]; then
    echo -e "${YELLOW}  /dev/hailo0 not found — run: sudo reboot${NC}"
fi
