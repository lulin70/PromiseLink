#!/bin/bash
# Initialize Let's Encrypt SSL certificate for PromiseLink
#
# This script obtains the first SSL certificate from Let's Encrypt.
# After the first cert is issued, docker-compose.prod.yml's certbot
# container will handle automatic renewals.
#
# Usage: ./init-ssl.sh <domain> [email]
# Example: ./init-ssl.sh www.promiselink.cn admin@promiselink.cn
#
# Prerequisites:
#   - DNS A record for <domain> must point to this server
#   - Port 80 must be open (certbot standalone mode)
#   - nginx container must NOT be running (port 80 conflict)

set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain> [email]}"
EMAIL="${2:-admin@${DOMAIN#*.}}"  # Default: admin@promiselink.cn if domain is www.promiselink.cn

DEPLOY_DIR="/opt/promiselink"
CERT_DIR="${DEPLOY_DIR}/certbot/conf"
WWW_DIR="${DEPLOY_DIR}/certbot/www"

echo "=========================================="
echo "SSL Certificate Initialization"
echo "Domain: ${DOMAIN}"
echo "Email:  ${EMAIL}"
echo "=========================================="

# Step 0: Idempotency check — skip if cert already exists and is valid
CERT_PATH="${CERT_DIR}/live/${DOMAIN}/fullchain.pem"
KEY_PATH="${CERT_DIR}/live/${DOMAIN}/privkey.pem"
if [ -f "${CERT_PATH}" ] && [ -f "${KEY_PATH}" ]; then
    if openssl x509 -checkend 2592000 -noout -in "${CERT_PATH}" 2>/dev/null; then
        echo "--- Certificate already exists and is valid for >30 days. Skipping. ---"
        echo "  Cert: ${CERT_PATH}"
        echo "If you want to force re-issuance, delete the cert files first."
        exit 0
    fi
    echo "--- Certificate exists but expires soon. Re-issuing. ---"
fi

# Step 1: Stop nginx if running (free port 80)
echo "--- Step 1: Stop nginx container (free port 80) ---"
if docker ps --format '{{.Names}}' | grep -q promiselink-nginx; then
    docker stop promiselink-nginx 2>/dev/null || true
    echo "Stopped promiselink-nginx"
else
    echo "nginx container not running"
fi

# Step 2: Obtain certificate using standalone mode
echo "--- Step 2: Obtain certificate via certbot standalone ---"
mkdir -p "${CERT_DIR}" "${WWW_DIR}"
docker run --rm \
    -p 80:80 \
    -v "${CERT_DIR}:/etc/letsencrypt" \
    -v "${WWW_DIR}:/var/www/certbot" \
    certbot/certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    -d "${DOMAIN}" \
    -d "${DOMAIN#www.}" || \
docker run --rm \
    -p 80:80 \
    -v "${CERT_DIR}:/etc/letsencrypt" \
    -v "${WWW_DIR}:/var/www/certbot" \
    certbot/certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    -d "${DOMAIN}"

# Step 3: Verify certificate files exist
CERT_PATH="${CERT_DIR}/live/${DOMAIN}/fullchain.pem"
KEY_PATH="${CERT_DIR}/live/${DOMAIN}/privkey.pem"
if [ ! -f "${CERT_PATH}" ] || [ ! -f "${KEY_PATH}" ]; then
    echo "ERROR: Certificate files not found at ${CERT_PATH}"
    echo "Check certbot output above for errors"
    exit 1
fi

echo "--- Step 3: Certificate verified ---"
echo "  Cert: ${CERT_PATH}"
echo "  Key:  ${KEY_PATH}"

# Step 4: Restart full stack (nginx will pick up the cert)
echo "--- Step 4: Restart full stack ---"
cd "${DEPLOY_DIR}"
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml ps

# Step 5: Verify HTTPS
echo "--- Step 5: Verify HTTPS (waiting 10s for nginx to start) ---"
sleep 10
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${DOMAIN}/api/v1/health" || echo "000")
if [ "${HTTP_CODE}" = "200" ]; then
    echo "SUCCESS: https://${DOMAIN}/api/v1/health returned 200"
else
    echo "WARNING: https://${DOMAIN}/api/v1/health returned ${HTTP_CODE}"
    echo "Check nginx logs: docker compose -f docker-compose.prod.yml logs nginx"
fi

echo "=========================================="
echo "SSL initialization complete"
echo "=========================================="
