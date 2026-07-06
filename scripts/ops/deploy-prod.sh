#!/bin/bash
# Production deployment with automatic rollback on health check failure.
#
# Usage: ./deploy-prod.sh <remote-host> [remote-user] <version>
#
# Flow:
#   1. Record current image version (for rollback)
#   2. Backup SQLite database
#   3. Pull new image and restart
#   4. Health check (60s polling)
#   5. On failure: rollback to previous image + restore DB backup
#
# Exit codes:
#   0 — deployment healthy
#   1 — deployment failed, rollback executed
#   2 — deployment failed, rollback also failed (manual intervention needed)

set -euo pipefail

REMOTE_HOST="${1:?Usage: $0 <remote-host> [remote-user] <version>}"
REMOTE_USER="${2:-ubuntu}"
VERSION="${3:?Version required (e.g., 0.8.0)}"

COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="/opt/promiselink/backups"
DB_PATH="/opt/promiselink/data/promiselink.db"
DEPLOY_DIR="/opt/promiselink"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=========================================="
echo "Production deployment: v${VERSION}"
echo "Target: ${REMOTE_USER}@${REMOTE_HOST}"
echo "Time: ${TIMESTAMP}"
echo "=========================================="

# Step 1+2+3: Record version, backup, deploy on remote host
ssh "${REMOTE_USER}@${REMOTE_HOST}" bash -s << REMOTE_SCRIPT
set -euo pipefail
cd "${DEPLOY_DIR}"

echo "--- Step 1: Record current image version ---"
CURRENT_IMAGE=""
if docker compose -f "${COMPOSE_FILE}" images promiselink-api 2>/dev/null | grep -q promiselink; then
    CURRENT_IMAGE=\$(docker compose -f "${COMPOSE_FILE}" images promiselink-api 2>/dev/null | tail -1 | awk '{print \$2}')
    echo "Current image: \${CURRENT_IMAGE}"
    echo "\${CURRENT_IMAGE}" > "${DEPLOY_DIR}/.last-known-good"
else
    echo "No existing deployment found (first deploy)"
    echo "" > "${DEPLOY_DIR}/.last-known-good"
fi

echo "--- Step 2: Backup database ---"
mkdir -p "${BACKUP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/pre_deploy_\${TIMESTAMP}.db"
if [ -f "${DB_PATH}" ]; then
    sqlite3 "${DB_PATH}" ".backup '\${BACKUP_FILE}'" 2>/dev/null || cp "${DB_PATH}" "\${BACKUP_FILE}"
    gzip "\${BACKUP_FILE}"
    echo "Backup: \${BACKUP_FILE}.gz"
else
    echo "No DB file at ${DB_PATH} (first deploy or volume empty)"
fi

echo "--- Step 3: Pull new image v${VERSION} ---"
export VERSION="${VERSION}"
docker compose -f "${COMPOSE_FILE}" pull promiselink-api
echo "--- Step 3b: Restart with new version ---"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans
docker compose -f "${COMPOSE_FILE}" ps

echo "--- Step 4: Health check (up to 60s) ---"
HEALTH_OK=false
for i in \$(seq 1 60); do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo "Health check passed after \${i}s"
        HEALTH_OK=true
        break
    fi
    sleep 1
done

if [ "\$HEALTH_OK" = "true" ]; then
    echo "--- DEPLOYMENT SUCCESSFUL: v${VERSION} ---"
    echo "${VERSION}" > "${DEPLOY_DIR}/.current-version"
    exit 0
fi

echo "=========================================="
echo "HEALTH CHECK FAILED after 60s"
echo "=========================================="
echo "--- Container logs (last 80 lines) ---"
docker compose -f "${COMPOSE_FILE}" logs --tail=80 promiselink-api

echo "=========================================="
echo "INITIATING ROLLBACK"
echo "=========================================="

PREV_IMAGE=\$(cat "${DEPLOY_DIR}/.last-known-good" 2>/dev/null || echo "")
if [ -z "\$PREV_IMAGE" ]; then
    echo "ERROR: No previous version recorded — cannot auto-rollback"
    echo "Manual intervention required. Container is still running with failed v${VERSION}"
    exit 2
fi

echo "Rolling back to: \$PREV_IMAGE"
# Extract version from image tag (after last colon)
PREV_VERSION=\$(echo "\$PREV_IMAGE" | rev | cut -d: -f1 | rev)
if [ -z "\$PREV_VERSION" ] || [ "\$PREV_VERSION" = "\$PREV_IMAGE" ]; then
    echo "Could not parse version from image tag, using 'latest'"
    PREV_VERSION="latest"
fi

export VERSION="\$PREV_VERSION"
docker compose -f "${COMPOSE_FILE}" pull promiselink-api || echo "WARNING: Pull previous image failed"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans

echo "--- Step 5b: Restore database backup ---"
LATEST_BACKUP=\$(ls -t "${BACKUP_DIR}"/pre_deploy_*.db.gz 2>/dev/null | head -1)
if [ -n "\$LATEST_BACKUP" ]; then
    gunzip -c "\$LATEST_BACKUP" > "${DB_PATH}"
    echo "DB restored from \$LATEST_BACKUP"
    docker compose -f "${COMPOSE_FILE}" restart promiselink-api
    sleep 5
else
    echo "WARNING: No backup found — cannot restore DB. Schema may be inconsistent."
fi

# Verify rollback health
ROLLBACK_OK=false
for i in \$(seq 1 30); do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo "Rollback health check passed after \${i}s"
        ROLLBACK_OK=true
        break
    fi
    sleep 1
done

if [ "\$ROLLBACK_OK" = "true" ]; then
    echo "--- ROLLBACK SUCCESSFUL: restored to \$PREV_VERSION ---"
    echo "\$PREV_VERSION" > "${DEPLOY_DIR}/.current-version"
    exit 1
else
    echo "=========================================="
    echo "CRITICAL: ROLLBACK ALSO FAILED"
    echo "Manual intervention required at ${REMOTE_HOST}"
    echo "Container logs:"
    docker compose -f "${COMPOSE_FILE}" logs --tail=30 promiselink-api
    echo "=========================================="
    exit 2
fi
REMOTE_SCRIPT

EXIT_CODE=$?
echo ""
echo "=========================================="
case $EXIT_CODE in
    0)
        echo "RESULT: v${VERSION} deployed successfully"
        ;;
    1)
        echo "RESULT: v${VERSION} failed, rolled back to previous version"
        ;;
    2)
        echo "RESULT: CRITICAL — v${VERSION} failed and rollback also failed"
        echo "Manual intervention required at ${REMOTE_HOST}"
        ;;
    *)
        echo "RESULT: Unexpected error (exit code $EXIT_CODE)"
        ;;
esac
echo "=========================================="
exit $EXIT_CODE
