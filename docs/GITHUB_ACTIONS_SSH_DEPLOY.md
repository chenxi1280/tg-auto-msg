# GitHub Actions + SSH 发布

这套方案不需要额外购买服务器。

工作方式是：

1. 代码 push 到 GitHub
2. GitHub Actions 在 GitHub 提供的 runner 上运行
3. runner 使用 SSH 连到生产机
4. runner 执行 `deploy/release.sh`
5. 生产机接收 release 包并完成 `docker compose` 更新

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
mkdir -p /data/tgmsg/shared/{postgres,redis,logs,uploads,nginx-logs}
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

## 四、Workflow 已做什么

仓库里的 workflow 文件：

- [.github/workflows/deploy-production.yml](/Users/xida/PycharmProjects/tg-auto-msg/.github/workflows/deploy-production.yml)

它会：

1. checkout 当前代码
2. 读取 GitHub Secrets
3. 写入 runner 的 SSH 配置
4. 调用 `bash deploy/release.sh --host production-server`

而 `deploy/release.sh` 会：

1. 校验当前分支
2. 用 `git archive` 生成干净 release 包
3. 上传到服务器 `/data/tgmsg/incoming`
4. 解压到 `/data/tgmsg/releases/<release_id>`
5. 调用 `deploy/server-install-release.sh`
6. 执行 `docker compose up -d --build --remove-orphans`
7. 更新 `/data/tgmsg/current`

## 五、怎么触发发布

支持两种方式：

### 1. 手动发布

GitHub 页面进入：

`Actions -> Deploy Production -> Run workflow`

### 2. 自动发布

当 `main` 或 `master` 有 push 时自动触发。

如果你担心误发布，可以先把 workflow 的 `push:` 去掉，只保留 `workflow_dispatch:`。

## 六、发布后怎么确认

在服务器执行：

```bash
readlink -f /data/tgmsg/current
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps
systemctl list-timers | grep tgmsg
```

看 release 是否切换成功，容器是否 healthy。

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
