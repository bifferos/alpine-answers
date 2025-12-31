#!/usr/bin/env bash
# Simple test harness using pvectl instead of test.py
# macOS-friendly (uses shasum), script-safe outputs, minimal glue

set -e
set -u
# Enable pipefail when available (bash, zsh)
set -o pipefail 2>/dev/null || true

# --- Config ---
VM_NAME="alpine-headless-test"
OVERLAY_ISO="headless_test_apkovl.iso"
# Storage for ISOs and disks
ISO_STORAGE="local"
DISK_STORAGE=${PVECTL_DEFAULT_DISK_STORAGE:-local-lvm}
# Network bridge (can be provided via PVECTL_DEFAULT_BRIDGE)
BRIDGE=${PVECTL_DEFAULT_BRIDGE:-vmbr1}
# pvectl binary (override with PVECTL env or edit to ./pvectl)
PVECTL=${PVECTL:-pvectl}
# Local build artifacts (align with prior test.py cleanup)
TARBALL_FILE="alpine.apkovl.tar.gz"
# VM resources
CORES=1
MEMORY_MIB=2048
DISK_SIZE="16G"

# --- Helpers ---
die() { echo "Error: $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

get_vmids_by_name() {
  local name="$1"
  # pvectl list --name prints VMIDs only, one per line
  "$PVECTL" list --name "$name" || true
}

ensure_single_vmid_or_none() {
  local name="$1"
  # Collect VMIDs as newline-delimited text (avoid bash4-only mapfile)
  local out
  out=$(get_vmids_by_name "$name")
  # Count non-empty lines
  local count
  count=$(printf "%s\n" "$out" | awk 'NF{c++} END{print c+0}')
  if [ "$count" -gt 1 ]; then
    # Join VMIDs into a single line for readability
    local joined
    joined=$(printf "%s\n" "$out" | paste -sd' ' -)
    echo "Multiple VMs found for name '$name': ${joined}" >&2
    echo "Refuse to proceed; please disambiguate or clean up manually." >&2
    exit 2
  fi
  echo "$count"
}


wait_until_off() {
  local vmid="$1"
  # Poll pvectl status --onoff until 'off'
  while true; do
    local state
    state=$("$PVECTL" status "$vmid" --onoff || echo "unknown")
    if [[ "$state" == "off" ]]; then
      break
    fi
    sleep 5
  done
}

# --- Cleanup (safe name handling) ---
# Remove local artifacts from previous runs (mirrors test.py cleanup)
rm -f "$TARBALL_FILE" "$OVERLAY_ISO"

count=$(ensure_single_vmid_or_none "$VM_NAME")
if [[ "$count" == "1" ]]; then
  VMID_TO_REMOVE=$(get_vmids_by_name "$VM_NAME")
  echo "Removing existing VM ${VM_NAME} (VMID ${VMID_TO_REMOVE})..." >&2
  "$PVECTL" remove "$VMID_TO_REMOVE"
else
  echo "No existing VM named ${VM_NAME}; continuing" >&2
fi

# Delete prior overlay ISO if present
if "$PVECTL" iso list --storage "$ISO_STORAGE" | grep -Fx "$OVERLAY_ISO" >/dev/null; then
  echo "Deleting existing overlay ISO ${OVERLAY_ISO} from ${ISO_STORAGE}..." >&2
  "$PVECTL" iso delete --storage "$ISO_STORAGE" --name "$OVERLAY_ISO"
fi

# --- Build the overlay ISO ---
if [[ ! -x ./alpine-answers ]]; then
  die "Missing or non-executable ./alpine-answers"
fi
./alpine-answers --hostname "$VM_NAME" --iso "$OVERLAY_ISO"

# --- Ensure Alpine ISO present; upload overlay ISO ---
ALPINE_ISO=$(python3 ./alpine-latest)
if ! "$PVECTL" iso list --storage "$ISO_STORAGE" | grep -Fx "$ALPINE_ISO" >/dev/null; then
  echo "Alpine ISO ${ALPINE_ISO} not present; downloading and uploading..." >&2
  python3 ./alpine-latest --fetch --dir .
  "$PVECTL" iso upload --storage "$ISO_STORAGE" --file "$ALPINE_ISO"
else
  echo "Alpine ISO ${ALPINE_ISO} already present in ${ISO_STORAGE}" >&2
fi

# Upload the overlay ISO
"$PVECTL" iso upload --storage "$ISO_STORAGE" --file "$OVERLAY_ISO"

# --- Create VM ---
NEW_VMID=$("$PVECTL" create "$VM_NAME" --cores "$CORES" --memory "$MEMORY_MIB")
[[ -n "$NEW_VMID" ]] || die "Failed to obtain VMID from pvectl create"

echo "VM created: ${VM_NAME} (VMID ${NEW_VMID})" >&2


# --- Add disk and NIC ---
DISK_SLOT=$("$PVECTL" disk add "$NEW_VMID" --slot scsi0 --storage "$DISK_STORAGE" --size "$DISK_SIZE")
[[ -n "$DISK_SLOT" ]] || die "Failed to attach disk"

"$PVECTL" nic add "$NEW_VMID" --model virtio --bridge "$BRIDGE"

# --- Attach ISOs to CD/DVD drives (requires VM off) ---
"$PVECTL" cdrom add "$NEW_VMID" --slot ide0 --storage "$ISO_STORAGE" --iso "$ALPINE_ISO"
"$PVECTL" cdrom add "$NEW_VMID" --slot ide2 --storage "$ISO_STORAGE" --iso "$OVERLAY_ISO"

# --- Set boot order: disk first, then Alpine CD-ROM ---
"$PVECTL" options "$NEW_VMID" --boot "${DISK_SLOT},ide0"

# --- Start, wait for shutdown (installer completes), start again ---
"$PVECTL" start "$NEW_VMID"
wait_until_off "$NEW_VMID"
"$PVECTL" start "$NEW_VMID"

echo "Test sequence complete for VMID ${NEW_VMID}" >&2
