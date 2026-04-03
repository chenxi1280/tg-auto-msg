# 部署目录说明

`deploy/` 只放和发布、回滚、巡检、服务器运行环境相关的资产，不放业务代码。

## 目录职责

- `release.sh`
  - 本地标准发布入口，负责打包并推送 release 到服务器。
- `rollback.sh`
  - 线上版本回滚脚本。
- `server-install-release.sh`
  - 服务器端安装 release、切换软链、拉起服务。
- `compose-up.sh`
  - 统一封装 `docker compose` 启动流程。
- `docker-env.sh`
  - 生成或校验 Docker 所需环境变量。
- `check-services.sh`
  - 后端与基础服务健康检查。
- `check-frontend.sh`
  - 前端可用性巡检。
- `nginx/`
  - Nginx 配置。
- `systemd/`
  - 定时巡检与自愈相关的 service / timer 文件。

## 维护约定

1. 部署脚本尽量保持无状态，可重复执行。
2. 环境变量示例统一写入 `.env.docker.example` 或部署文档，不在脚本里硬编码业务密钥。
3. 新增运维脚本时，优先补充到 `docs/deployment/DEPLOYMENT.md`，并在本文件登记用途。
