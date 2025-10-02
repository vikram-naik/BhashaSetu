#!/usr/bin/env bash
set -euo pipefail

# =========================
# BhashaSetu DB Reset Script (with backup)
# =========================
# 1. Dumps current database schema+data into backups/
# 2. Drops all objects inside schema bhashasetu
# 3. Recreates schema + seeds baseline data
#
# Usage:
#   ./scripts/reset_db.sh
#
# Requirements:
#   - PostgreSQL installed
#   - Environment variables:
#       BHASHA_DB   (default: bhashasetu)
#       BHASHA_USER (default: bhasha_user)
#       BHASHA_HOST (default: localhost)
#       BHASHA_PASS (optional, if password auth enabled)

DB_NAME="${BHASHA_DB:-bhashasetu}"
DB_USER="${BHASHA_USER:-bhasha_user}"
DB_HOST="${BHASHA_HOST:-localhost}"

BACKUP_DIR="backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_backup_${TIMESTAMP}.sql"

echo "🔄 Resetting BhashaSetu database..."
echo "    DB:   $DB_NAME"
echo "    User: $DB_USER"
echo "    Host: $DB_HOST"

# Step 0: Ensure backup dir exists
mkdir -p "$BACKUP_DIR"

# Step 1: Backup current DB
echo "💾 Backing up database to $BACKUP_FILE..."
pg_dump -U "$DB_USER" -h "$DB_HOST" -d "$DB_NAME" > "$BACKUP_FILE" || {
    echo "⚠️ Backup failed! Aborting reset."
    exit 1
}

# Step 2: Drop existing objects (keep schema + user)
echo "🧹 Dropping old objects..."
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -f schema/drop_bhashasetu_objects.sql

# Step 3: Recreate schema
echo "📐 Recreating schema..."
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -f schema/bhashasetu.sql

# Step 4: Seed reference data
echo "🌱 Seeding baseline data..."
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -f seeds/bhashasetu-seed.sql
psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -f seeds/jparacrawl-seed.sql
echo "    Backup saved at: $BACKUP_FILE"
