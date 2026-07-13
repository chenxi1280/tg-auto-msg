# tgmsg 线上部署与目录说明

更新时间：`2026-04-11`

本文档记录 `tgmsg` 当前线上真实部署方式、目录结构、挂载关系和验收方法。

## 1. 当前发布方式

`tgmsg` 当前使用：

- GitHub Actions
- SSH 发布到服务器
- release 目录 + `current` 软链
- GitHub Actions 构建 Docker Image，服务器只 pull 指定镜像并 `docker compose up -d --no-build`

发布链路：

1. GitHub Actions `Deploy Production` workflow 触发 `deploy/release.sh`
2. 生成 release 包并上传到 `/data/tgmsg/incoming`
3. 解压到 `/data/tgmsg/releases/<release_id>`
4. 调用 `deploy/server-install-release.sh`
5. 切换 `/data/tgmsg/current`
6. 拉取 `tgmsg-app` 镜像、执行迁移、释放前端静态文件并启动 `tgmsg-app`

中间件不由本项目维护：

- PostgreSQL 由 `infra-compose` 提供
- Redis 由 `infra-compose` 提供
- 两者通过 `infra_default` 网络暴露服务名 `postgres` / `redis`

生产环境发布约束：

- **主流程**：生产发布应优先通过 GitHub Actions `Deploy Production`
- 本地 `deploy/release.sh` 对生产环境会先输出强提醒，并要求显式传入 `--confirm-production-deploy` 才允许继续
- 本地直发仅用于紧急修复；发生这种情况后，必须立即把同样的修复补回 Git 提交，避免下一次 Actions 发布覆盖生产
- 不允许长期只修改 `/data/tgmsg/current` 而不回补仓库

## 2. 当前线上目录

```text
/data/tgmsg
├── backups/
├── current -> /data/tgmsg/releases/<release_id>
├── incoming/
├── logs/
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
- 仓库中的一次性运维脚本不会被 GitHub Actions 自动执行；是否执行完全取决于运维人员手动调用。

## 3. 当前真实挂载

| 容器 | 容器内路径 | 宿主机路径 | 说明 |
|------|------------|------------|------|
| `tgmsg-app` | `/app/logs` | `/data/tgmsg/logs` | 后端日志 |
| `tgmsg-app` | `/app/uploads` | `/data/tgmsg/uploads` | 上传目录 |
注意：

- 线上当前真实挂载目录是 `/data/tgmsg/logs`、`/data/tgmsg/uploads`
- 这和一些较早文档里提到的 `/data/tgmsg/shared/logs` 并不一致
- 本文档与当前线上实际保持一致
- 后端镜像当前不会自动复制仓库根目录下的 `scripts/` 到容器内；一次性脚本不会因为发布而自动进入运行时镜像

## 4. 当前关键配置

`/data/tgmsg/shared/.env` 至少包含：

```env
DATABASE_URL=postgresql+asyncpg://<db_user>:<db_password>@postgres:5432/tgmsg
REDIS_URL=redis://:<redis_password>@redis:6379/0
INFRA_NETWORK_NAME=infra_default
TGMSG_APP_BIND_HOST=127.0.0.1
TGMSG_APP_HOST_PORT=18000
TGMSG_FRONTEND_STATIC_BASE_DIR=/data/infra/www/msg.telema.cn
H5_BASE_URL=https://msg.telema.cn
GHCR_USERNAME=<github_user>
GHCR_TOKEN=<github_pat_with_read_packages>
PROVINCE_CODE=<province_code>
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_PASSWORD=<strong_password>
ADMIN_BOOTSTRAP_DISPLAY_NAME=超级管理员
ENCRYPTION_KEY=<base64_32byte_key>
ENCRYPTION_KEY_FALLBACKS=<old_base64_32byte_key_comma_separated>
SCHEDULER_TASK_TIMEOUT_SECONDS=240
SCHEDULER_TASK_CONCURRENCY=3
```

含义：

- `DATABASE_URL` 指向 `infra-compose` 中的 `postgres`
- `REDIS_URL` 指向 `infra-compose` 中的 `redis`
- `INFRA_NETWORK_NAME` 用于把业务容器接入公共网络
- `TGMSG_APP_*` 让后端只监听本机端口，由宿主机 Nginx 将 `/api/` 反代过来
- `TGMSG_FRONTEND_STATIC_BASE_DIR` 是 H5 静态 release 目录
- `H5_BASE_URL` 应使用公网子域名
- `PROVINCE_CODE` 表示当前这套服务所属省份，超管账号按省份隔离初始化
- `ADMIN_BOOTSTRAP_*` 用于首次启动时自动创建当前省份的首个 `super_admin`
- `ENCRYPTION_KEY` 必须长期稳定保存；如需轮换，先把旧密钥放入 `ENCRYPTION_KEY_FALLBACKS`，确认历史账号会话可解密后再发布，避免线上用户被迫重新绑定。
- `SCHEDULER_TASK_TIMEOUT_SECONDS` 控制单个定时任务最大执行时长。超过后调度器会释放 processing 锁并继续后续任务，避免一个任务卡住所有定时发送。
- `SCHEDULER_TASK_CONCURRENCY` 控制单轮最多并发执行的到点任务数。默认 `3`，用于避免多个慢任务按 240 秒串行拖住整个发送队列。

### 4.1 调度器即时检测

后台管理员可调用：

```bash
curl -fsS -H "Authorization: Bearer <admin_jwt>" \
  https://msg.telema.cn/api/admin/system/scheduler-health
```

关键判断：

- `status=healthy` 表示当前没有发现调度积压异常。
- `issues` 包含 `due_tasks_not_queued` 表示数据库已有到点 scheduled 任务，但 Redis pending/processing 都为空，调度器可能已经停摆。
- `issues` 包含 `pending_tasks_stale` 表示 Redis 中有到点任务长时间未被 consumer 消费。
- `last_task_timeout_id` 不为空表示最近有单个任务执行超过 `SCHEDULER_TASK_TIMEOUT_SECONDS`，调度器已中断该次执行并继续处理后续任务。

## 5. 当前实际 vs 目标架构

目标架构：

- 所有业务统一使用共享数据库子账号 `app_user`
- 业务在发布时确保自己的数据库存在

当前线上实际：

- `tgmsg` 已切换为共享业务账号 `app_user`
- `infra-compose` 的管理员入口已切换为 `postgres`
- PostgreSQL 与 Redis 数据目录已经迁移到 `/data/infra/postgres` 和 `/data/infra/redis`
- `/data/tgmsg/postgres` 与 `/data/tgmsg/redis` 仍保留为回退副本

当前仍保留的兼容点主要是 `tgmsg` 自己的日志和上传目录仍位于 `/data/tgmsg/*`。

公共入口由基础设施服务器宿主机 Nginx 提供，H5 静态文件由 `/data/infra/www/msg.telema.cn/current` 托管，`/api/` 反代到 `127.0.0.1:18000`。

## 6. 发布后验收清单

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
test -f /data/infra/www/msg.telema.cn/current/index.html
curl -fsS http://127.0.0.1:${TGMSG_APP_HOST_PORT:-18000}/openapi.json
curl -fsS -H 'Host: msg.telema.cn' http://127.0.0.1/ >/dev/null
test "$(curl -k -s -o /dev/null -w '%{http_code}' -H 'Host: msg.telema.cn' https://127.0.0.1/api/admin-auth/me)" = "401"
docker logs --tail 50 tgmsg-app
docker inspect tgmsg-app --format '{{json .Mounts}}'
readlink -f /data/tgmsg/current
```

通过标准：

- `tgmsg-app` 是 `Up`
- H5 静态首页、OpenAPI 与宿主机 `/api` 反代均可访问
- `tgmsg-app` 日志中没有持续重启或连接失败
- `current` 指向最新 release
- 更新 sing-box 订阅后，必须从 `tgmsg-app` 通过每个启用的 SOCKS 网关完成一次 Telegram MTProto 请求；仅 SOCKS 端口 TCP 可连接不代表代理可发送 Telegram 消息

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

## 8. 定时重启

线上安装 `tgmsg-scheduled-restart.timer`，默认每周三 `04:20 Asia/Shanghai` 执行一次，只重启当前 release 的 `app` 服务：

```bash
systemctl list-timers 'tgmsg-scheduled-restart*'
journalctl -u tgmsg-scheduled-restart.service -n 100 --no-pager
tail -n 100 /data/tgmsg/shared/logs/scheduled-restart.log
```

重启动作通过 `/data/tgmsg/current/deploy/scheduled-restart.sh` 执行，脚本会：

- 使用 `/data/tgmsg/current` 和 `/data/tgmsg/shared/.env`
- 通过 `docker compose up -d --no-build --force-recreate app` 重建业务容器
- 等待 `tgmsg-app` healthy
- 验证本机 OpenAPI 与宿主机 `/api` 反代
- 使用 `/run/tgmsg-scheduled-restart.lock` 避免并发执行

如需临时关闭：

```bash
systemctl disable --now tgmsg-scheduled-restart.timer
```

如需不禁用 timer 但跳过执行：

```bash
mkdir -p /etc/tgmsg
printf 'TGMSG_SCHEDULED_RESTART_ENABLED=0\n' > /etc/tgmsg/scheduled-restart.env
systemctl daemon-reload
```
