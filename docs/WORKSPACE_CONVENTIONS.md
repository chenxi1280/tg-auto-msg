# 仓库整理约定

这份文档用于约束后续文件摆放，避免仓库再次变乱。

## 根目录只保留什么

根目录只保留以下高频入口：

- 启动入口：`main.py`
- 构建与运行入口：`docker-compose.yml`
- 依赖与环境样例：`requirements.txt`、`.env.example`、`.env.docker.example`
- 总导航文档：`README.md`

不应继续把以下内容直接堆在根目录：

- 架构说明
- 部署手册
- 阶段性总结
- 临时排查笔记
- 数据库操作说明

## 目录归属规则

- `docs/`
  - 全部说明文档与规范文档。
- `deploy/`
  - 发布、回滚、巡检、Nginx、systemd 资产。
- `scripts/`
  - 本地维护脚本与辅助启动脚本。
- `docker/`
  - Docker 镜像构建文件。
- `sql/`
  - 基线 SQL、开发初始化 SQL、增量迁移 SQL。
- `backend/`
  - Python 后端业务代码。
- `frontend/h5/`
  - H5 前端工程。
- `logs/`、`uploads/`
  - 运行期产物，不纳入版本控制。

## 命名建议

1. 文档优先放到 `docs/` 对应主题目录，不新增新的根目录 Markdown 文件。
2. 架构文档统一收敛到 `docs/architecture/`。
3. 新的部署说明统一收敛到 `docs/deployment/`。
4. 面向开发者的初始化、迁移、结构说明统一收敛到 `docs/setup/`。
5. 阶段性总结、复盘、历史交付材料统一放 `docs/history/`。
6. 辅助 `.py` / `.sh` 统一放 `scripts/`，`Dockerfile*` 统一放 `docker/`。

## 清理规则

1. 不提交 `__pycache__/`、`.DS_Store`、日志、上传文件、虚拟环境。
2. 新增工具或脚本时，优先复用现有目录，不随手创建 `temp/`、`misc/`、`test2/` 之类模糊目录。
3. 如果某个文件暂时不知道放哪，优先补文档说明后再落位，不直接放根目录。
