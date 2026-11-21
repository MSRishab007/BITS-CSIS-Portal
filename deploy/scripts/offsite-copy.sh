#!/usr/bin/env bash
# Copy the backups to another machine (run after the nightly backup).
# Backups that only live on the same server don't survive a disk failure.
#
#   sudo -u portal bash deploy/scripts/offsite-copy.sh backupuser@10.1.2.3:/backups/asset-portal/
#
# Needs an SSH key for the portal user on the destination (see DEPLOYMENT.md).
set -euo pipefail
DEST="${1:?Usage: offsite-copy.sh user@host:/path/}"
rsync -a --delete /srv/asset-portal/backups/ "$DEST"
echo "Backups copied to $DEST"
