# 分支与发布规范

更新时间：`2026-04-11`

本文档记录 `tgmsg` 当前真实在用的分支模型与发布入口。

## 1. 当前真实分支职责

当前仓库不是 `master` 直接自动上线，而是：

- `master`
  - 主要开发主干
  - 合并功能与修复
  - `pull_request` 与 `push master` 只跑 `Python Checks`
- `release`
  - 当前生产发布分支
  - `push release` 会触发 `Deploy Production`
- `feature/<name>`
  - 新功能分支
- `fix/<name>`
  - 缺陷修复分支
- `ops/<name>`
  - 运维、发布、脚本与基础设施调整

## 2. 当前标准发布节奏

推荐节奏：

1. 在 `feature/*` 或 `fix/*` 开发
2. 提交 PR，合入 `master`
3. `master` 上通过 `Python Checks`
4. 需要上线时，把已确认要发布的提交同步到 `release`
5. push `release`，触发 `Deploy Production`

这意味着：

- `master` 是主要集成分支
- `release` 是当前生产发布入口
- 生产上线不依赖本地手工覆盖目录

## 3. 当前发布入口

当前标准生产发布入口只有两种：

### 自动发布

```bash
git push origin release
```

### 手动发布

GitHub 页面：

```text
Actions -> Deploy Production -> Run workflow
```

当前不推荐把下面这条命令当作标准日常入口：

```bash
bash deploy/release.sh --host 47.250.167.174
```

它现在只保留为应急修复入口，并且对生产环境会要求显式确认：

```bash
bash deploy/release.sh --host 47.250.167.174 --confirm-production-deploy
```

## 4. 发布目录模型

服务器基准目录为：

```text
/data/tgmsg
├── current -> /data/tgmsg/releases/<release_id>
├── releases/
├── incoming/
├── backups/
├── shared/
│   └── .env
├── logs/
├── uploads/
└── nginx-logs/
```

说明：

- `releases/` 保存每次发版的只读源码
- `current` 指向当前正在运行的版本
- `incoming/` 保存上传的 release 包
- `shared/.env` 保存线上环境变量
- `logs/uploads` 保存运行期持久化数据，前端静态文件由 `/data/infra/www/msg.telema.cn` 托管

## 5. 当前发布脚本行为

当前标准发布链路是：

1. GitHub Actions 调用 `deploy/release.sh`
2. `deploy/release.sh` 生成 release 包并上传服务器
3. 服务器执行 `deploy/server-install-release.sh`
4. 拉取指定 GHCR 镜像，更新 `tgmsg-app`，并释放前端静态文件
5. 成功后切换 `current`

数据库和 Redis 不跟随本仓库发版：

- PostgreSQL：独立 `infra-compose`
- Redis：独立 `infra-compose`

## 6. 回滚

统一回滚命令：

```bash
bash /data/tgmsg/current/deploy/rollback.sh <release-id>
```

先查看已有版本：

```bash
ls -lah /data/tgmsg/releases
```

## 7. 不再推荐的做法

以下方式都不再作为标准发布流程：

- 手工覆盖 `/data/tgmsg/current`
- 直接覆盖旧的应用目录
- 上传整个本地目录而不是使用 `git archive`
- 未提交代码就直接改线上
- 把本地应急发版长期当成主路径

## 8. 后续可选演进

后续如果要继续简化流程，可以考虑把：

- `master` 既作为开发主干，也作为唯一发布主干

但这是未来可选优化，不是当前真实线上流程。当前仍以：

- `master` 做检查
- `release` 做部署

为准。
