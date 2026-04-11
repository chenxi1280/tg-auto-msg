# GitHub Actions + SSH 发布

更新时间：`2026-04-11`

这份文档只描述当前 `tgmsg` 的标准线上发布方式：

- GitHub Actions 负责检查与触发发布
- SSH 负责把 release 包送到生产机
- 生产机使用 `deploy/release.sh` 和 `deploy/server-install-release.sh` 完成上线

## 1. 当前工作方式

当前仓库的发布链路如下：

1. 代码合入 `main`
2. `pull_request` 与 `push main` 运行 `Python Checks`
3. `push release` 或手动点击 `Deploy Production`
4. `Deploy Production` 先重新运行：
   - `ruff`
   - `pylint`
   - `python -m unittest discover -s tests -t .`
5. 检查通过后，workflow 通过 SSH 调用 `deploy/release.sh`
6. 生产机收到 release 包并完成容器更新

重要结论：

- `main` 当前不会自动部署
- `release` 是当前自动部署分支
- 手动 `workflow_dispatch` 也会先检查再部署

## 2. 需要的 GitHub 配置

进入：

```text
Settings -> Secrets and variables -> Actions
```

### 必填 Secrets

- `PRODUCTION_SSH_PRIVATE_KEY`
- `PRODUCTION_HOST`
- `PRODUCTION_USER`

### 可选 Secret

- `PRODUCTION_PORT`

### 可选 Variables

- `PRODUCTION_BASE_DIR`
  - 默认 `/data/tgmsg`
- `RELEASE_BRANCHES`
  - 默认 `release main master`

## 3. 首次准备服务器

### 3.1 配置 SSH 免密

本地生成部署专用密钥：

```bash
ssh-keygen -t ed25519 -C "github-actions-tgmsg" -f ~/.ssh/tgmsg_github_actions
```

把公钥加入服务器：

```bash
ssh-copy-id -i ~/.ssh/tgmsg_github_actions.pub root@47.250.167.174
```

本地验证：

```bash
ssh -i ~/.ssh/tgmsg_github_actions root@47.250.167.174
```

### 3.2 准备目录与环境文件

```bash
mkdir -p /data/tgmsg/{releases,shared,incoming,backups}
mkdir -p /data/tgmsg/{logs,uploads,nginx-logs}
cp .env.docker.example /data/tgmsg/shared/.env
vi /data/tgmsg/shared/.env
```

`.env` 至少补齐：

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

当前线上约定：

- PostgreSQL 与 Redis 由独立 `infra-compose` 项目维护
- `DATABASE_URL` / `REDIS_URL` 应指向 `infra_default` 网络中的 `postgres` / `redis`

## 4. Workflow 当前做什么

仓库内的 workflow 文件：

- [.github/workflows/python-checks.yml](/Users/xida/PycharmProjects/tg-auto-msg/.github/workflows/python-checks.yml)
- [.github/workflows/deploy-production.yml](/Users/xida/PycharmProjects/tg-auto-msg/.github/workflows/deploy-production.yml)

### `Python Checks`

触发：

- `pull_request`
- `push main`

动作：

- Python `3.11`
- 安装 `requirements-dev.txt`
- 运行 Ruff / Pylint / unittest

### `Deploy Production`

触发：

- `push release`
- `workflow_dispatch`

动作：

1. 使用 Python `3.11`
2. 再次运行 Ruff / Pylint / unittest
3. 校验生产 Secrets
4. 生成 SSH 配置
5. 调用：

```bash
bash deploy/release.sh --host production-server --base-dir "${PRODUCTION_BASE_DIR:-/data/tgmsg}"
```

## 5. 服务器侧实际执行什么

`deploy/release.sh` 会：

1. 检查分支和工作区
2. `git archive` 生成干净发布包
3. 上传到 `/data/tgmsg/incoming/<release_id>.tar.gz`
4. 解压到 `/data/tgmsg/releases/<release_id>`
5. 调用 `deploy/server-install-release.sh`

`deploy/server-install-release.sh` 会：

1. 准备 shared 目录
2. 准备 `/data/tgmsg/shared/.env`
3. 调用 `deploy/compose-up.sh`
4. 确保业务数据库存在
5. 构建 `app` 和 `frontend`
6. 执行数据库迁移
7. 启动 `tgmsg-app`
8. 启动 `tgmsg-frontend`
9. 更新 `/data/tgmsg/current`
10. 安装并启用巡检 timer

当前 `docker-compose.yml` 只更新业务容器：

- `tgmsg-app`
- `tgmsg-frontend`

## 6. 如何触发

### 自动触发

```bash
git push origin release
```

### 手动触发

GitHub 页面：

```text
Actions -> Deploy Production -> Run workflow
```

## 7. 发布后确认

在服务器上执行：

```bash
readlink -f /data/tgmsg/current
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps
curl -fsS http://127.0.0.1/ >/dev/null && echo ok
docker logs --tail 100 tgmsg-app
systemctl list-timers | grep tgmsg
```

如果需要看线上真实挂载与目录，请再对照：

- `docs/deployment/PRODUCTION_RUNTIME.md`

## 8. 回滚

```bash
bash /data/tgmsg/current/deploy/rollback.sh <release-id>
```

先查看 release 列表：

```bash
ls -lah /data/tgmsg/releases
```

## 9. 本地直发生产的定位

本地仍然可以调用：

```bash
bash deploy/release.sh --host 47.250.167.174 --confirm-production-deploy
```

但它不是默认主路径，只用于应急修复。

出现这种情况后，必须把相同改动补回 Git，并通过标准 GitHub Actions 流程再发布一次，避免线上与仓库状态漂移。
