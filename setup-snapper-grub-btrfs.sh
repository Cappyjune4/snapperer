#!/bin/bash
#
# setup-snapper-grub-btrfs.sh
#
# Sets up snapper + grub-btrfs on a btrfs root, works with either the
# Mint/Ubuntu-desktop @ / @home subvolume layout, or a flat top-level
# subvolume root (subvolid=5, subvol=/), as used by curtin/Ubuntu Server
# autoinstall.
#
# Assumes: the btrfs partition already exists and / is already mounted
# on it. This script does NOT touch partitioning, run this AFTER the OS
# install is complete and you've booted into it.
#
# Usage:
#   chmod +x setup-snapper-grub-btrfs.sh
#   sudo ./setup-snapper-grub-btrfs.sh
#   sudo ./setup-snapper-grub-btrfs.sh --target-user=someone   # skip SUDO_USER detection
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo ./setup-snapper-grub-btrfs.sh"
  exit 1
fi

TARGET_USER=""
for arg in "$@"; do
  case "$arg" in
  --target-user=*) TARGET_USER="${arg#--target-user=}" ;;
  *)
    echo "Unknown option: $arg"
    echo "Usage: $0 [--target-user=NAME]"
    exit 1
    ;;
  esac
done

# Figure out the non-root user who invoked sudo, so we can chown .snapshots
# correctly. --target-user takes priority since pkexec (unlike sudo) doesn't
# set SUDO_USER at all, so a GUI invoking this via pkexec must pass it
# explicitly instead of relying on this env var.
if [[ -z "$TARGET_USER" ]]; then
  TARGET_USER="${SUDO_USER:-}"
fi
if [[ -z "$TARGET_USER" ]]; then
  echo "Couldn't detect the invoking user (SUDO_USER is empty)."
  read -rp "Enter the username .snapshots should be owned by: " TARGET_USER
fi
echo "==> Using target user: ${TARGET_USER}"

echo "==> Sanity check: confirming btrfs root"
ROOT_FSTYPE="$(findmnt -no FSTYPE /)"
if [[ "$ROOT_FSTYPE" != "btrfs" ]]; then
  echo "ERROR: / is not btrfs (found: ${ROOT_FSTYPE}). Aborting."
  exit 1
fi
ROOT_SUBVOL="$(findmnt -no OPTIONS / | tr ',' '\n' | grep '^subvol=' | cut -d= -f2)"
echo "    Root subvolume: ${ROOT_SUBVOL:-/}"
btrfs subvolume list /

echo ""
echo "==> Step 1: Installing snapper, inotify-tools, git, make, gawk"
apt update
apt install -y snapper inotify-tools git make gawk

echo ""
echo "==> Step 2: Making gawk the default awk (mawk breaks grub-btrfs's UUID parsing)"
# update-alternatives --config is interactive; set it non-interactively instead
update-alternatives --set awk /usr/bin/gawk
awk --version | head -1

echo ""
echo "==> Step 3: Building grub-btrfs from source (not packaged for Ubuntu/Mint)"
BUILD_DIR="$(mktemp -d)"
git clone https://github.com/Antynea/grub-btrfs.git "${BUILD_DIR}/grub-btrfs"
(cd "${BUILD_DIR}/grub-btrfs" && make install)
rm -rf "${BUILD_DIR}"

echo ""
echo "==> Step 4: Creating snapper root config"
if [[ ! -f /etc/snapper/configs/root ]]; then
  snapper -c root create-config /
else
  echo "    /etc/snapper/configs/root already exists, skipping create-config"
fi

echo ""
echo "==> Step 5: Fixing .snapshots permissions (root:${TARGET_USER}, 750)"
chmod 750 /.snapshots
chown "root:${TARGET_USER}" /.snapshots

echo ""
echo "==> Step 6: Enabling snapper timeline + cleanup timers"
systemctl enable --now snapper-timeline.timer
systemctl enable --now snapper-cleanup.timer

echo ""
echo "==> Step 7: Enabling grub-btrfsd (auto-updates GRUB menu on new snapshots)"
systemctl enable --now grub-btrfsd.service

echo ""
echo "==> Step 8: Regenerating GRUB config"
update-grub

echo ""
echo "==> Step 9: Verifying everything"
echo "--- systemd units ---"
systemctl is-enabled snapper-timeline.timer snapper-cleanup.timer grub-btrfsd.service
echo "--- .snapshots permissions ---"
ls -la /.snapshots
echo "--- apt hook (should be present, ships with Mint's snapper package) ---"
if [[ -f /etc/apt/apt.conf.d/*snapper* ]] 2>/dev/null || ls /etc/apt/apt.conf.d/*snapper* >/dev/null 2>&1; then
  echo "    Found apt snapshot hook."
else
  echo "    WARNING: No apt snapper hook found under /etc/apt/apt.conf.d/"
fi
echo "--- timeline / retention settings ---"
grep -E "TIMELINE|NUMBER" /etc/snapper/configs/root

echo ""
echo "==> Done. Snapper + grub-btrfs setup complete."
echo "    Reboot and check the GRUB menu for a 'Btrfs snapshots' submenu to confirm."
