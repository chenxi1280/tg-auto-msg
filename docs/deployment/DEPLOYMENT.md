# 部署指南

更新时间：`2026-04-11`

本文档只描述当前 `tgmsg` 的标准生产发布路径。当前线上默认方式是：

- GitHub Actions
- SSH 发布到服务器
- `release` 目录 + `current` 软链
- Docker Compose 更新 `tgmsg-app`，前端镜像释放为宿主机静态文件

如果你要看服务器真实目录、挂载和运行状态，请同时参考：

- `docs/GITHUB_ACTIONS_SSH_DEPLOY.md`
- `docs/deployment/PRODUCTION_RUNTIME.md`

## 1. 当前标准发布流程

标准链路如下：

1. 开发分支合入 `main`
2. `pull_request` 与 `main` 自动运行 `Python Checks`
3. 需要上线时，push 到 `release`，或手动触发 `Deploy Production`
4. `Deploy Production` 在 GitHub Actions 中再次运行：
   - `ruff`
   - `pylint`
   - `python -m unittest discover -s tests -t .`
5. 检查通过后，workflow 通过 SSH 调用 `deploy/release.sh`
6. 服务器接收 release 包，执行 `deploy/server-install-release.sh`
7. 服务器拉取指定 GHCR 镜像，完成数据库迁移、释放前端静态文件、更新容器、切换 `/data/tgmsg/current`

当前 CI、容器和推荐本地环境统一使用 `Python 3.11`。

## 2. GitHub Actions 触发规则

当前仓库有两条相关 workflow：

- `Python Checks`
  - 触发：`pull_request`、`push main`
  - 用途：只检查，不部署
- `Deploy Production`
  - 触发：`push release`、手动 `workflow_dispatch`
  - 用途：先检查，再发布

这意味着：

- `main` 不会自动上线
- `release` 才是当前生产发布入口
- 手动点 `Deploy Production` 也会先跑同一套检查

## 3. 发布前准备

### 3.1 GitHub Secrets / Variables

仓库 `Settings -> Secrets and variables -> Actions` 至少需要：

必填 Secrets：

- `PRODUCTION_SSH_PRIVATE_KEY`
- `PRODUCTION_HOST`
- `PRODUCTION_USER`
- `GHCR_TOKEN`

可选 Secret：

- `PRODUCTION_PORT`
- `GHCR_USERNAME`

可选 Variables：

- `PRODUCTION_BASE_DIR`
  - 默认 `/data/tgmsg`
- `RELEASE_BRANCHES`
  - 默认 `release main master`

### 3.2 服务器目录

首次准备服务器时，至少需要：

```bash
mkdir -p /data/tgmsg/{releases,shared,incoming,backups}
mkdir -p /data/tgmsg/{logs,uploads}
```

线上环境变量文件位于：

```bash
/data/tgmsg/shared/.env
```

### 3.3 线上环境变量

可以从仓库模板初始化：

```bash
cp .env.docker.example /data/tgmsg/shared/.env
vi /data/tgmsg/shared/.env
```

至少需要补齐：

```env
TG_API_ID=
TG_API_HASH=
BOT_TOKEN=
DATABASE_URL=
REDIS_URL=
JWT_SECRET_KEY=
ADMIN_API_TOKEN=
ADMIN_BOOTSTRAP_USERNAME=
ADMIN_BOOTSTRAP_PASSWORD=
```

当前生产环境约定：

- `DATABASE_URL` 指向独立基础设施项目中的 PostgreSQL
- `REDIS_URL` 指向独立基础设施项目中的 Redis
- 业务容器通过 `infra_default` 网络访问 `postgres` / `redis`

## 4. 服务器侧发布过程

`Deploy Production` 最终会调用：

```bash
bash deploy/release.sh --host production-server --base-dir /data/tgmsg
```

`deploy/release.sh` 会完成：

1. 校验当前分支和工作区状态
2. 用 `git archive` 生成干净 release 包
3. 上传到 `/data/tgmsg/incoming/<release_id>.tar.gz`
4. 解压到 `/data/tgmsg/releases/<release_id>`
5. 调用 `deploy/server-install-release.sh`

`deploy/server-install-release.sh` 会继续完成：

1. 准备 `releases/shared/incoming/backups` 目录
2. 准备 `/data/tgmsg/shared/.env`
3. 执行 `deploy/compose-up.sh`
4. 确保业务数据库存在
5. 拉取 Actions 推送的指定 GHCR 镜像
6. 执行数据库迁移
7. 释放前端静态文件到 `/data/infra/www/msg.telema.cn`
8. 启动 `tgmsg-app`
9. 切换 `/data/tgmsg/current`
10. 安装并启用巡检相关 systemd timer

当前 `docker-compose.yml` 只负责业务容器：

- `tgmsg-app`

前端镜像不作为长期运行容器；公网 `80/443` 由基础设施服务器宿主机 Nginx 托管静态文件，并按 `msg.telema.cn` 转发 `/api/`。

中间件不由本仓库发版：

- PostgreSQL：独立 `infra-compose`
- Redis：独立 `infra-compose`

## 5. 线上目录与挂载

当前以服务器实际运行结果为准，核心目录是：

```text
/data/tgmsg
├── backups/
├── current -> /data/tgmsg/releases/<release_id>
├── incoming/
├── logs/
├── releases/
├── shared/
│   └── .env
└── uploads/
```

当前业务容器真实挂载：

- `tgmsg-app:/app/logs` -> `/data/tgmsg/logs`
- `tgmsg-app:/app/uploads` -> `/data/tgmsg/uploads`

如果文档与服务器不一致，以：

- `docker-compose.yml`
- `deploy/compose-up.sh`
- `docs/deployment/PRODUCTION_RUNTIME.md`

三者交叉确认后的实际结果为准。

## 6. 如何触发发布

### 自动发布

push 到 `release`：

```bash
git push origin release
```

### 手动发布

在 GitHub 页面执行：

```text
Actions -> Deploy Production -> Run workflow
```

## 7. 发布后验收

推荐在服务器执行：

```bash
readlink -f /data/tgmsg/current
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps
test -f /data/infra/www/msg.telema.cn/current/index.html
curl -fsS http://127.0.0.1:${TGMSG_APP_HOST_PORT:-18000}/openapi.json >/dev/null && echo ok
curl -fsS -H 'Host: msg.telema.cn' http://127.0.0.1/ >/dev/null && echo ok
docker logs --tail 100 tgmsg-app
systemctl list-timers | grep tgmsg
```

通过标准：

- `tgmsg-app` 是 `running`
- 静态首页与 OpenAPI 可访问
- 后端日志没有持续报错或循环重启
- `current` 已指向新 release

## 8. 回滚

回滚入口：

```bash
bash /data/tgmsg/current/deploy/rollback.sh <release_id>
```

先查看可用版本：

```bash
ls -lah /data/tgmsg/releases
```

## 9. 本地直发生产的约束

本地直接执行：

```bash
bash deploy/release.sh --host 47.250.167.174
```

不再是标准生产入口。

当前只允许用于应急修复，并且脚本会要求显式确认：

```bash
bash deploy/release.sh --host 47.250.167.174 --confirm-production-deploy
```

如果走了这条应急路径，必须把同样修复立即补回 Git，并通过正常 Actions 发布覆盖一次，避免线上状态漂移。

## 10. 历史方案说明

仓库里仍能看到 Supervisor、systemd、手工 tar 包等历史部署痕迹，但它们都不是当前标准生产方案。

当前应遵循的唯一默认主路径是：

- GitHub Actions `Deploy Production`
- `deploy/release.sh`
- `deploy/server-install-release.sh`
- `/data/tgmsg/releases` + `/data/tgmsg/current`
