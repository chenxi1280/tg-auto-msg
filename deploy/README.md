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
- `ensure-database.sh`
  - 使用共享业务子账号连接 infra PostgreSQL，确保本项目数据库存在。
- `docker-env.sh`
  - 生成或校验 Docker 所需环境变量。
- `check-services.sh`
  - 后端容器、宿主机前端入口、基础设施健康检查、自愈和告警。
- `check-frontend.sh`
  - 宿主机 Nginx 前端入口可用性巡检。
- `nginx/`
  - Nginx 配置。
- `systemd/`
  - 定时巡检与自愈相关的 service / timer 文件。

## 维护约定

1. 部署脚本尽量保持无状态，可重复执行。
2. 环境变量示例统一写入 `.env.docker.example` 或部署文档，不在脚本里硬编码业务密钥。
3. 生产部署不在服务器构建镜像，只拉取 GitHub Actions 推送到 GHCR 的指定 tag。
4. 前端镜像只作为静态产物载体，服务器释放到 `/data/infra/www/msg.telema.cn`，由宿主机 Nginx 托管。
5. 新增运维脚本时，优先补充到 `docs/deployment/DEPLOYMENT.md`，并在本文件登记用途。
