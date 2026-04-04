#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/docker-env.sh"

ensure_runtime_env

echo "==> 发布目录: $APP_DIR"
echo "==> 环境文件: $ENV_FILE"

echo "==> 确保业务数据库存在"
bash "$SCRIPT_DIR/ensure-database.sh"

echo "==> 预构建核心服务镜像（app + frontend）"
compose build app frontend

echo "==> 执行数据库迁移"
compose run --rm --no-deps app python -m backend.database.runtime.migration_cli apply

echo "==> 启动核心服务（app + frontend）"
compose up -d --remove-orphans app frontend

echo "==> 检查容器状态"
compose ps

frontend_status="$(docker inspect tgmsg-frontend --format '{{.State.Status}}' 2>/dev/null || true)"
frontend_health="$(docker inspect tgmsg-frontend --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

if [[ "$frontend_status" != "running" || "$frontend_health" == "unhealthy" || "$frontend_status" == "created" || "$frontend_status" == "exited" ]]; then
  echo "⚠️ frontend 当前状态异常: status=${frontend_status:-unknown}, health=${frontend_health:-none}"
  echo "==> 尝试补拉 tgmsg-frontend"
  docker start tgmsg-frontend >/dev/null 2>&1 || compose up -d frontend
  sleep 3
fi

services=(
  tgmsg-app
  tgmsg-frontend
)

for service in "${services[@]}"; do
  status="$(docker inspect "$service" --format '{{.State.Status}}' 2>/dev/null || true)"
  health="$(docker inspect "$service" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"

  if [[ "$status" != "running" ]]; then
    echo "❌ 服务未运行: $service (status=${status:-missing})" >&2
    exit 1
  fi
  if [[ -n "$health" && "$health" != "healthy" && "$health" != "starting" ]]; then
    echo "❌ 服务健康检查失败: $service (health=$health)" >&2
    exit 1
  fi
  echo "✅ $service status=$status health=${health:-none}"
done

echo "✅ 完整部署检查完成"
