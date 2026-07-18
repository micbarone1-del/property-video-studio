#!/bin/bash
# backup_jobs.sh -- standalone, independent snapshot of the jobs/ directory.
# Deliberately lives outside the git repo and outside
# /var/www/property-video-studio entirely, so it can never be accidentally
# touched by a repo-scoped command (git operations, patch scripts, etc).
#
# Creates a timestamped, immutable tarball snapshot -- NOT a live mirror --
# so a future deletion mistake can never propagate into this backup. The
# only deletions this script ever performs are of its OWN old backup
# files (matching jobs_*.tar.gz, older than RETENTION_DAYS), inside
# BACKUP_DIR only. It never touches SOURCE_DIR.
set -e

BACKUP_DIR="/var/backups/pvs_jobs"
SOURCE_PARENT="/var/www/property-video-studio"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y-%m-%d_%H%M)

mkdir -p "$BACKUP_DIR"

if [ -d "$SOURCE_PARENT/jobs" ]; then
    tar czf "$BACKUP_DIR/jobs_${TIMESTAMP}.tar.gz" -C "$SOURCE_PARENT" jobs/
    SIZE=$(du -h "$BACKUP_DIR/jobs_${TIMESTAMP}.tar.gz" | cut -f1)
    echo "$(date '+%Y-%m-%d %H:%M:%S') backup created: jobs_${TIMESTAMP}.tar.gz ($SIZE)" >> "$BACKUP_DIR/backup.log"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIPPED: $SOURCE_PARENT/jobs does not exist" >> "$BACKUP_DIR/backup.log"
    exit 0
fi

# Only ever deletes files matching this exact pattern, inside BACKUP_DIR --
# never touches the live jobs/ directory.
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -name "jobs_*.tar.gz" -mtime +${RETENTION_DAYS} -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') pruned $DELETED backup(s) older than ${RETENTION_DAYS} days" >> "$BACKUP_DIR/backup.log"
fi
