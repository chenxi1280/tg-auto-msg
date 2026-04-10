# GitHub Actions + SSH 发布

这套方案不需要额外购买服务器。

工作方式是：

1. 代码 push 到 GitHub
2. `pull_request` 与 `main` 使用 `Python Checks` 做代码检查
3. `release` 分支触发 `Deploy Production`
4. deploy runner 先执行 `ruff`、`pylint`、`unittest`
5. 检查通过后，runner 使用 SSH 连到生产机并执行 `deploy/release.sh`
6. 生产机接收 release 包并完成 `docker compose` 更新

## 适用范围

当前这份配置针对 `tgmsg` 项目，默认发布目录为 `/data/tgmsg`。

如果要给 `tggrouprobot` 也接一套 GitHub Actions，可以复用同样模式，只需要：

- 单独一份仓库内 workflow
- 单独一个 `PRODUCTION_BASE_DIR=/data/tggrouprobot`
- 单独的 release / rollback 脚本

## 一、先准备服务器 SSH Key 登录

GitHub Actions 不适合用密码 SSH，推荐改成密钥登录。

### 1. 在本地生成部署专用私钥

```bash
ssh-keygen -t ed25519 -C "github-actions-tgmsg" -f ~/.ssh/tgmsg_github_actions
```

会生成：

- 私钥：`~/.ssh/tgmsg_github_actions`
- 公钥：`~/.ssh/tgmsg_github_actions.pub`

### 2. 把公钥加到服务器

如果先继续使用 `root`：

```bash
ssh-copy-id -i ~/.ssh/tgmsg_github_actions.pub root@47.250.167.174
```

如果没有 `ssh-copy-id`，就手工追加到服务器：

```bash
cat ~/.ssh/tgmsg_github_actions.pub
```

把输出追加到服务器 `/root/.ssh/authorized_keys`。

### 3. 本地验证密钥可登录

```bash
ssh -i ~/.ssh/tgmsg_github_actions root@47.250.167.174
```

验证通过后，再配置 GitHub Secrets。

## 二、配置 GitHub Secrets 和 Variables

打开 GitHub 仓库：

`Settings -> Secrets and variables -> Actions`

### 必填 Secrets

- `PRODUCTION_SSH_PRIVATE_KEY`
  - 内容填 `~/.ssh/tgmsg_github_actions` 私钥全文
- `PRODUCTION_HOST`
  - 例如 `47.250.167.174`
- `PRODUCTION_USER`
  - 当前可先填 `root`

### 可选 Secret

- `PRODUCTION_PORT`
  - 默认是 `22`

### 可选 Variables

- `PRODUCTION_BASE_DIR`
  - 默认 `/data/tgmsg`
- `RELEASE_BRANCHES`
  - 默认 `main master`
  - 如果你完成了 `main` 迁移，建议只填 `main`

## 三、第一次发布前的服务器准备

先在服务器上准备 shared 目录：

```bash
mkdir -p /data/tgmsg/{releases,shared,incoming,backups}
mkdir -p /data/tgmsg/shared/{logs,uploads,nginx-logs}
```

然后准备线上环境文件：

```bash
cp /data/tgmsg/app/.env /data/tgmsg/shared/.env
```

如果你已经想切到更规范的生产配置，也可以改成：

```bash
cp /data/tgmsg/app/.env.docker.example /data/tgmsg/shared/.env
vi /data/tgmsg/shared/.env
```

注意：

- `tgmsg` 不再自行启动 `postgres` / `redis`
- `DATABASE_URL` 与 `REDIS_URL` 必须指向独立的基础设施项目
- 默认约定为连接 `infra_default` 网络内的 `postgres` / `redis`
- `DATABASE_URL` 推荐使用共享业务子账号，例如 `app_user`
- 发布脚本会在启动容器前自动确保 `tgmsg` 数据库存在

## 四、Workflow 已做什么

仓库里的 workflow 文件：

- [.github/workflows/python-checks.yml](/Users/xida/PycharmProjects/tg-auto-msg/.github/workflows/python-checks.yml)
- [.github/workflows/deploy-production.yml](/Users/xida/PycharmProjects/tg-auto-msg/.github/workflows/deploy-production.yml)

其中：

1. `Python Checks`
   - 在 `pull_request`、`push main` 时运行
   - 使用 Python `3.11`
   - 执行 `ruff`、`pylint`、`unittest`
2. `Deploy Production`
   - 支持手动 `workflow_dispatch`
   - 在 `push release` 时自动触发
   - workflow 内先跑 `ruff`、`pylint`、`unittest`
   - 然后读取 GitHub Secrets、写入 SSH 配置，并调用 `bash deploy/release.sh --host production-server`

而 `deploy/release.sh` 会：

1. 校验当前分支
2. 用 `git archive` 生成干净 release 包
3. 上传到服务器 `/data/tgmsg/incoming`
4. 解压到 `/data/tgmsg/releases/<release_id>`
5. 调用 `deploy/server-install-release.sh`
6. 执行 `docker compose up -d --build --remove-orphans`
7. 更新 `/data/tgmsg/current`

当前 `tgmsg` 的 `docker-compose.yml` 只会更新：

- `app`
- `frontend`

数据库与 Redis 由独立的 `infra-compose` 维护。

## 五、怎么触发发布

支持两种方式：

### 1. 手动发布

GitHub 页面进入：

`Actions -> Deploy Production -> Run workflow`

### 2. 自动发布

当 `release` 有 push 时，会直接触发 `Deploy Production`；该 workflow 会先检查，再部署。
`main` 上只运行检查，不会自动部署。

## 六、发布后怎么确认

在服务器执行：

```bash
readlink -f /data/tgmsg/current
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps
systemctl list-timers | grep tgmsg
```

看 release 是否切换成功，容器是否 healthy。

当前线上目录、挂载和验收清单，见：

- `docs/deployment/PRODUCTION_RUNTIME.md`

## 七、回滚

如果某次发布有问题：

```bash
bash /data/tgmsg/current/deploy/rollback.sh <release-id>
```

可先查看已有版本：

```bash
ls -lah /data/tgmsg/releases
```

## 八、推荐下一步

现在这套已经可以用，但还有两件事建议尽快做：

- 把默认发布分支从 `master` 迁移到 `main`
- 给 `tggrouprobot` 做同样一套 workflow 和 release 结构
