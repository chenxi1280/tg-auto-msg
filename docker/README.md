# Docker 目录说明

`docker/` 统一存放镜像构建文件，避免多个 `Dockerfile*` 散落在根目录。

## 当前文件

- `Dockerfile.backend`
  - 后端 API 镜像。
- `Dockerfile.frontend`
  - 前端 Nginx 镜像。

## 维护约定

1. `docker-compose.yml` 继续保留在根目录作为运行入口。
2. 新增构建文件统一放 `docker/`，并在 compose 或 CI 中显式引用。
