# tgmsg 线上部署与目录说明

更新时间：`2026-04-04`

本文档记录 `tgmsg` 当前线上真实部署方式、目录结构、挂载关系和验收方法。

## 1. 当前发布方式

`tgmsg` 当前使用：

- GitHub Actions
- SSH 发布到服务器
- release 目录 + `current` 软链
- `docker compose up -d --build --remove-orphans`

发布链路：

1. GitHub Actions 触发 `deploy/release.sh`
2. 生成 release 包并上传到 `/data/tgmsg/incoming`
3. 解压到 `/data/tgmsg/releases/<release_id>`
4. 调用 `deploy/server-install-release.sh`
5. 切换 `/data/tgmsg/current`
6. 启动 `tgmsg-app` 与 `tgmsg-frontend`

中间件不由本项目维护：

- PostgreSQL 由 `infra-compose` 提供
- Redis 由 `infra-compose` 提供
- 两者通过 `infra_default` 网络暴露服务名 `postgres` / `redis`

## 2. 当前线上目录

```text
/data/tgmsg
├── backups/
├── current -> /data/tgmsg/releases/<release_id>
├── incoming/
├── logs/
├── nginx-logs/
├── postgres/
├── redis/
├── releases/
├── shared/
│   └── .env
└── uploads/
```

说明：

- `/data/tgmsg/shared/.env` 是本项目权威环境变量文件。
- `/data/tgmsg/current` 指向当前运行版本。
- `/data/tgmsg/incoming` 存放 Actions 上传的 release 包。
- `/data/tgmsg/backups` 存放归档与备份材料。
- `/data/tgmsg/postgres` 和 `/data/tgmsg/redis` 现仅保留为历史回退副本，不再被运行中的 `infra-compose` 容器挂载。

## 3. 当前真实挂载

| 容器 | 容器内路径 | 宿主机路径 | 说明 |
|------|------------|------------|------|
| `tgmsg-app` | `/app/logs` | `/data/tgmsg/logs` | 后端日志 |
| `tgmsg-app` | `/app/uploads` | `/data/tgmsg/uploads` | 上传目录 |
| `tgmsg-frontend` | `/var/log/nginx` | `/data/tgmsg/nginx-logs` | 前端 Nginx 日志 |

注意：

- 线上当前真实挂载目录是 `/data/tgmsg/logs`、`/data/tgmsg/uploads`、`/data/tgmsg/nginx-logs`
- 这和一些较早文档里提到的 `/data/tgmsg/shared/logs` 并不一致
- 本文档与当前线上实际保持一致

## 4. 当前关键配置

`/data/tgmsg/shared/.env` 至少包含：

```env
DATABASE_URL=postgresql+asyncpg://<db_user>:<db_password>@postgres:5432/tgmsg
REDIS_URL=redis://:<redis_password>@redis:6379/0
INFRA_NETWORK_NAME=infra_default
```

含义：

- `DATABASE_URL` 指向 `infra-compose` 中的 `postgres`
- `REDIS_URL` 指向 `infra-compose` 中的 `redis`
- `INFRA_NETWORK_NAME` 用于把业务容器接入公共网络

## 5. 当前实际 vs 目标架构

目标架构：

- 所有业务统一使用共享数据库子账号 `app_user`
- 业务在发布时确保自己的数据库存在

当前线上实际：

- `tgmsg` 已切换为共享业务账号 `app_user`
- `infra-compose` 的管理员入口已切换为 `postgres`
- PostgreSQL 与 Redis 数据目录已经迁移到 `/data/infra/postgres` 和 `/data/infra/redis`
- `/data/tgmsg/postgres` 与 `/data/tgmsg/redis` 仍保留为回退副本

当前仍保留的兼容点主要是 `tgmsg` 自己的日志、上传和 Nginx 日志目录仍位于 `/data/tgmsg/*`。

## 6. 发布后验收清单

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
curl -fsS http://127.0.0.1/ >/dev/null && echo ok
docker logs --tail 50 tgmsg-app
docker inspect tgmsg-app --format '{{json .Mounts}}'
docker inspect tgmsg-frontend --format '{{json .Mounts}}'
readlink -f /data/tgmsg/current
```

通过标准：

- `tgmsg-app` 与 `tgmsg-frontend` 都是 `Up`
- 首页 `http://127.0.0.1/` 可访问
- `tgmsg-app` 日志中没有持续重启或连接失败
- `current` 指向最新 release

## 7. 常用运维命令

```bash
# 查看当前版本
readlink -f /data/tgmsg/current

# 查看 release 列表
ls -lah /data/tgmsg/releases

# 查看上传包
ls -lah /data/tgmsg/incoming

# 检查 compose 状态
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps

# 回滚
bash /data/tgmsg/current/deploy/rollback.sh <release_id>
```
