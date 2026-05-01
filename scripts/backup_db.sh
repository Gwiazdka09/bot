#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-data/footstats_backtest.db}"
BUCKET="${BUCKET_NAME:?BUCKET_NAME env var required}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
DEST="gs://${BUCKET}/backups/footstats_backtest_${TIMESTAMP}.db"
LATEST="gs://${BUCKET}/backups/footstats_backtest_latest.db"

echo "Backing up $DB_PATH → $DEST"
gcloud storage cp "$DB_PATH" "$DEST"
gcloud storage cp "$DB_PATH" "$LATEST"
echo "Backup complete: $DEST"
