#!/bin/bash
# Deploy PromiseLink to staging environment
set -e

REMOTE_HOST="${1:?Usage: $0 <remote-host>}"
REMOTE_USER="${2:-ubuntu}"
COMPOSE_FILE="docker-compose.hosted-poc.yml"

echo "Deploying PromiseLink to $REMOTE_USER@$REMOTE_HOST..."

# 1. Copy necessary files
scp docker-compose.hosted-poc.yml $REMOTE_USER@$REMOTE_HOST:/opt/promiselink/
scp .env.poc.hosted.example $REMOTE_USER@$REMOTE_HOST:/opt/promiselink/.env
scp -r nginx/ $REMOTE_USER@$REMOTE_HOST:/opt/promiselink/
scp -r frontend/dist/ $REMOTE_USER@$REMOTE_HOST:/opt/promiselink/static/h5/

# 2. Pull latest image and restart
# 批次3.5: 健康检查改为轮询 + 失败立即退出（原 sleep 10 + WARNING 不阻断部署，导致 broken 镜像被当成功）
ssh $REMOTE_USER@$REMOTE_HOST << 'EOF'
set -e
cd /opt/promiselink
docker compose -f docker-compose.hosted-poc.yml pull
docker compose -f docker-compose.hosted-poc.yml up -d --remove-orphans
docker compose -f docker-compose.hosted-poc.yml ps
echo "Waiting for health check (up to 30s)..."
HEALTH_OK=false
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo "Health check passed after ${i}s"
    HEALTH_OK=true
    break
  fi
  sleep 1
done
if [ "$HEALTH_OK" != "true" ]; then
  echo "ERROR: Health check failed after 30s — deployment unhealthy, rolling back"
  echo "--- Container logs (last 50 lines) ---"
  docker compose -f docker-compose.hosted-poc.yml logs --tail=50
  echo "--- Exiting with error ---"
  exit 1
fi
EOF

echo "Deployment complete and healthy!"
