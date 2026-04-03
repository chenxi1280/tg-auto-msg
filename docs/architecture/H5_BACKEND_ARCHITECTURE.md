# H5 Backend Architecture

## 分层

- `backend/h5_backend/app/`
  - 应用装配：工厂、生命周期、静态站点挂载。
- `backend/h5_backend/routers/`
  - 仅负责参数绑定、鉴权注入、调用 service。
- `backend/h5_backend/services/`
  - 按域拆分的业务实现：
  - `account/service.py`
  - `auth/service.py`
  - `login/service.py`
  - `proxy/service.py`
  - `task/{service,payload,serializers,helpers}.py`
- `backend/h5_backend/dependencies.py`
  - 跨域权限校验和共享依赖。

## 设计规则

1. `app/` 不写业务逻辑，只做应用生命周期和挂载。
2. `routers/` 不写业务逻辑，只做 HTTP 适配。
3. 业务逻辑集中在 `services/<domain>/service.py`。
4. `task` 子域的 payload/serializer/helper 与 service 分离，避免单文件膨胀。
