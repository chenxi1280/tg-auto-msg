# 分支与发布规范

本文档定义本项目推荐使用的分支模型和标准发布入口，目标是解决以下问题：

- 线上代码来源不透明，靠手工覆盖目录发布
- `.env`、日志、上传目录和源码目录耦合在一起
- `master` / `main` 混用，发布入口不统一
- 线上缺少可回滚、可审计的版本目录

## 推荐分支模型

推荐尽快统一到 `main` 作为唯一发布主干分支。

- `main`
  - 生产发布主干
  - 只有通过评审或自测完成的代码才允许合入
- `feature/<name>`
  - 新功能分支
- `fix/<name>`
  - 缺陷修复分支
- `ops/<name>`
  - 运维、部署、脚本和配置变更
- `release/<version>`
  - 仅在需要冻结预发布版本时使用，可选

## 从 `master` 迁移到 `main`

如果仓库还停留在 `master`，建议按下面流程迁移：

```bash
git checkout master
git pull origin master
git branch -m master main
git push origin main
git push origin --delete master
```

然后把 GitHub 默认分支切换到 `main`。

如果短期内暂时不能迁移，`deploy/release.sh` 仍兼容从 `master` 发布，但会给出警告。

## 标准发布目录

服务器基准目录为 `/data/tgmsg`，推荐结构如下：

```text
/data/tgmsg
├── current -> /data/tgmsg/releases/20260403_abcdef1
├── releases/
│   ├── 20260403_abcdef1/
│   └── 20260403_bcdefa2/
├── shared/
│   ├── .env
│   ├── logs/
│   ├── uploads/
│   └── nginx-logs/
├── incoming/
└── backups/
```

说明：

- `releases/` 保存每次发版的只读源码
- `current` 指向当前正在运行的版本
- `shared/` 保存不应随版本切换而丢失的配置和持久化数据
- `postgres` / `redis` 建议由独立的 `infra-compose` 项目维护，不再耦合在 `tgmsg` 发版里

## 标准发布入口

本地发布统一使用：

```bash
bash deploy/release.sh --host 47.250.167.174
```

该脚本会执行：

1. 校验当前分支和工作区状态
2. 使用 `git archive` 生成干净的发布包
3. 上传到服务器 `incoming/`
4. 解压到 `releases/<release_id>/`
5. 调用 `deploy/server-install-release.sh`
6. 构建并启动 Docker 服务
7. 成功后切换 `current` 软链

## 回滚

服务器上统一使用：

```bash
bash /data/tgmsg/current/deploy/rollback.sh <release-id>
```

例如：

```bash
bash /data/tgmsg/current/deploy/rollback.sh 20260403_abcdef1
```

## 发布前检查

建议每次发布前执行：

```bash
git status
git branch --show-current
bash deploy/release.sh --host 47.250.167.174
```

## 不再推荐的做法

以下做法建议停止使用：

- 手工 `tar.gz` 整个本地目录后上传覆盖
- 直接覆盖 `/data/tgmsg/app`
- 把 `.env` 跟随源码版本一起移动
- 在未提交代码的情况下直接上线
