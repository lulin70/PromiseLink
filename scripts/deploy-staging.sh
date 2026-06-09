#!/bin/bash
# Deploy EventLink to staging environment
set -e

REMOTE_HOST="${1:?Usage: $0 <remote-host>}"
REMOTE_USER="${2:-ubuntu}"
COMPOSE_FILE="docker-compose.hosted-poc.yml"

echo "Deploying EventLink to $REMOTE_USER@$REMOTE_HOST..."

# 1. Copy necessary files
scp docker-compose.hosted-poc.yml $REMOTE_USER@$REMOTE_HOST:/opt/eventlink/
scp .env.poc.hosted $REMOTE_USER@$REMOTE_HOST:/opt/eventlink/.env
scp -r nginx/ $REMOTE_USER@$REMOTE_HOST:/opt/eventlink/
scp -r static/h5/ $REMOTE_USER@$REMOTE_HOST:/opt/eventlink/static/h5/

# 2. Pull latest image and restart
ssh $REMOTE_USER@$REMOTE_HOST << 'EOF'
cd /opt/eventlink
docker compose -f docker-compose.hosted-poc.yml pull
docker compose -f docker-compose.hosted-poc.yml up -d --remove-orphans
docker compose -f docker-compose.hosted-poc.yml ps
echo "Waiting for health check..."
sleep 10
curl -sf http://localhost:8000/api/v1/health || echo "WARNING: Health check failed!"
EOF

echo "Deployment complete!"
