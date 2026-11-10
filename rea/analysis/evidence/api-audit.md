# API 独立覆盖率与鉴权审计

审计对象：安装器内 `app/server.pyc`，SHA-256 `55118631849817f20088c30894d94a7c84bff79d03eebe7af4b545c478ee5b0c`。方法：xdis 逐条枚举模块级字节码中的 `app.get/post/delete/...` 装饰器；没有导入、执行目标程序，也没有请求任何接口。

可复核脚本：[audit_local_routes.py](../tools/audit_local_routes.py)。独立结果：[audited-routes.json](audited-routes.json)。参数详细抽取由文档代理单独完成：[local-routes.json](local-routes.json)。两份结果按 `(method, path, handler)` 集合比对，缺失 **0**，多出 **0**。

## 1. 数量与“全部”的边界

| 范围 | 数量 | 说明 |
|---|---:|---|
| 显式注册 method/path | 70 | GET 40、POST 29、DELETE 1 |
| 显式唯一 path | 67 | `/admin/keys` 有 3 种方法；`/dl/config` 有 2 种方法 |
| `/dl` 与 `/dl/*` 显式路由 | 49 | 下载器 UI、任务、剧库、授权、更新等 |
| 安装版中间件允许继续处理的显式路由 | 50 | 上述 49 个加 `/img`；仍须满足后续鉴权及参数校验 |
| 被安装版中间件直接屏蔽的显式路由 | 20 | 如 `/search`、`/play`、`/stream`、`/admin/*`，返回 404 |
| 框架默认路由对象 | 4 | `/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc`，各 GET/HEAD |
| 合计注册 method/path（含框架） | 78 | 70 + 4 × 2；共 74 个路由对象、71 个唯一 path |

**不能把 70 个静态注册接口表述成 70 个安装版可用接口。** `server.py` 源行 661 的最前置判断在 `_PACKAGED_BUILD` 成立时只放行 `/dl`、以 `/dl/` 开头的路径、`/img`、`/favicon.ico`。`/favicon.ico` 只出现在豁免列表，没有显式路由注册，不能据此添加一个业务 API。[server.dis.txt](server.dis.txt:6698)

`_PACKAGED_BUILD = bool(getattr(LIC, '_PACKAGED', False))`；`licensing._is_packaged()` 以能否导入随包的 `_buildinfo` 或 `_integrity` 识别安装版，这两份模块确实随样本提供。因此安装器正常启动落入安装版分支是静态证据支持的推断，没有在 Windows 上进行运行确认。[server.dis.txt](server.dis.txt:791)、[licensing.dis.txt](licensing.dis.txt:608)

框架版本为随包的 **FastAPI 0.141.1**，不是以本机环境或网上现行版本推测。已从安装器提取并逐文件验证 manifest SHA-256：

- [FastAPI METADATA](../extracted/python/Lib/site-packages/fastapi-0.141.1.dist-info/METADATA)
- [FastAPI 默认路径与 setup](../extracted/python/Lib/site-packages/fastapi/applications.py:1105)：默认参数只被调用方设置 `title`、`version`，四个默认端点均注册。
- [Starlette Route](../extracted/python/Lib/site-packages/starlette/routing.py:224)：这些框架端点默认 GET 并加入 HEAD。
- [FastAPI 业务路由方法处理](../extracted/python/Lib/site-packages/fastapi/routing.py:1019)：显式 `@app.get` 不因此自动增加 HEAD，故业务计数仍是 70。

安装版会在中间件层把上述四个框架端点全部屏蔽为 404。在非安装版分支，`/docs`、`/openapi.json`、`/redoc` 豁免 API key；`/docs/oauth2-redirect` 不在 `_EXEMPT` 中，会落入 API-key 校验。

## 2. 本地鉴权顺序与权限边界

以下均为 bytecode 直接观察，不含任何实际 token 值。总入口为 `auth_mw`，源行 654–708。[server.dis.txt](server.dis.txt:6698)

1. **安装版可见性过滤**：前述路径白名单，其余 404。这先于所有 token 校验，因此 admin token 或 API key 不会让安装版的旧 API 路由重新可达。
2. **Host 校验**：当 `BIND_HOST` 是空字符串、`127.0.0.1` 或 `localhost` 时，非空 Host 必须匹配 `127.0.0.1[:PORT]` 或 `localhost[:PORT]`，否则 403 `bad host`。默认 PORT 是 8000，但启动器会选择可用端口，不能把它当作保证不变的地址。
3. **跨站校验**：`/dl*`、`/admin*`、`/img`、`/stats` 拒绝 `Sec-Fetch-Site: cross-site`；非空 Origin 必须是 `http://127.0.0.1:<PORT>` 或 `http://localhost:<PORT>`，否则 403 `cross-site request blocked`。这不是一套全局 CORS 放行策略。
4. **UI 会话 token**：若 `HG_UI_TOKEN` 配置非空，`/dl*` 除 `/dl` 与 `/dl/status` 外均需要它。先取 Cookie `hg_ui_<PORT>`，没有非空 Cookie 才取 `x-hg-token` 请求头。使用 `hmac.compare_digest` 比较，失败 403 `unauthorized (open the app window)`。
5. **admin/API key 分流**：`/stats` 与 `/admin*` 跳过普通 API-key 校验，具体管理处理函数再检查 admin token。其余不在 `_EXEMPT` 的路径取 `x-api-key` 请求头，或 `api_key` query，交给 `KeyStore.is_valid` 验证；失败 401。
6. **普通 API-key 限流**：按 key 保留 60 秒窗口，默认 `RATE_PER_MIN=120`，达到上限返回 429。这个限流不适用于已经豁免的 `/dl/*`。

UI token、admin token、普通 API key、Java signer token、商业授权 key 是不同凭据，不可互换。

### UI 两个特例

- `GET /dl` 可以返回页面；仅当 query `k` 与已有 UI token 正确匹配时，才返回 303 到 `/dl` 并种 Cookie：`Path=/dl`、`HttpOnly`、`SameSite=strict`。启动器每次生成 UI token 并通过 `HG_UI_TOKEN` 传入服务。[server.dis.txt](server.dis.txt:23439)、[app.dis.txt](app.dis.txt:12296)
- `GET /dl/status` 虽然豁免中间件 UI 校验，处理函数自己调用 `_ui_token_ok`。无有效 token 只返回 `{"running": bool}`；有效 token 才返回完整任务与日志字段。不能把它标成“匿名读取所有状态”。[server.dis.txt](server.dis.txt:13572)

### 管理凭据与本地 API key

`_check_admin` 从 `x-admin-token` header 或 `admin_token` query 读取。`GET /stats`、`GET/POST/DELETE /admin/keys`、`POST /admin/keys/revoke` 显式调用它，失败 401；`GET /admin` 只是管理 HTML 页面，本身没有该处理函数检查（但安装版仍屏蔽所有 `/admin`）。`ADMIN_TOKEN` 未配置时在服务启动时随机生成，而不是空 token 放行。[server.dis.txt](server.dis.txt:6175)、[server.dis.txt](server.dis.txt:1089)

`KeyStore.is_valid` 要求 key 非空、与存储记录一致且 `enabled` 为真，通过后更新内存中的 `last_used`。存储默认是模块旁的 `apikeys.json`（可配置 `APIKEYS_PATH`）。这与商业授权校验不是同一个数据库或操作。[apikeys.dis.txt](apikeys.dis.txt:846)

## 3. 请求数据模型审计

在 **18 个已提取应用 Python 模块、1266 个递归 code object** 中搜索框架符号：仅 `server.pyc` 模块级引用 `FastAPI`/`uvicorn`；没有业务 `BaseModel`、`APIRouter`、`include_router`、`add_api_route`、`add_route`、`Flask`、`HTTPServer`、`socketserver` 或 `require_key` 引用。具体扫描模块与命中记录已保存到 `audited-routes.json.scanned_modules`。

所以这个样本**没有可以列出的自定义 Pydantic 请求类**。接口参数来自以下两层：

- 函数签名里的 `str/int/bool` query、`Query(...)` 默认值及约束、注入的 `Request`，或者 `dict` / `Body(...)` JSON body。
- 处理函数对 JSON dict 做 `.get(...)`、`or` 回退、类型转换、白名单或正则校验；这些才决定业务字段。不要把 `dict` 内字段伪造为已有 Pydantic schema，也不要把 `Query(...)` 或 `Body(...)` 中的 Ellipsis 当成可选默认值。

逐条签名、参数位置、类型、默认值见独立文档代理的 `local-routes.json.parameters`；本审计对其路由集合做了 0 差异核对。此集合核对不等价于逐项证明其中所有人工写出的响应 schema。

可直接复核的共用设置模型：`_dl_settings(payload)` 接收 `quality`，`series`（缺键时回退 `series_at_once`），`episodes`（缺键时回退 `concurrency`），交给 `offline_dl.dl_settings` 归一化；输出 `quality, series, episodes, workers=series*episodes, max_conn`。这里的 `.get(k, fallback)` 只在缺键时用别名，并非主键存在且为 null 时也用别名。[server.dis.txt](server.dis.txt:10015)

## 4. 商业授权不是全局路由中间件

`auth_mw` 不检查商业 license。`LIC.check_download` 的调用点是下载提交 `dl_submit`、下载工作线程 `_dl_worker`，以及剧库更新线程 `_lib_worker`（后者作为更新过程的许可回调）；不是所有搜索/目录/预览读取统一检查的全局依赖。

`licensing.check_download(series_id)`：当已许可且缓存仍有效时返回允许；否则调用授权后端的 `check_download` RPC，含设备与剧 ID 并附加安全参数。异常时返回 `allowed=false, licensed=false, reason='offline'`；后端返回的免费额度计数被更新到本地缓存。提交下载时若部分剧被拒绝，响应会带 `blocked/need_license/free_limit/free_used` 等字段；不能只凭 HTTP 200 判定授权成功。[licensing.dis.txt](licensing.dis.txt:5029)、[server.dis.txt](server.dis.txt:11345)

授权管理路由也有实际副作用：activate/deactivate/reactivate 修改许可状态；`GET /dl/license/purchase-poll` 在订单状态合适时会调用 `LIC.activate`。因此不能把全部 GET 请求称为只读。此审计没有调用这些接口。[server.dis.txt](server.dis.txt:24374)

## 5. 其他服务与剩余边界

Python 业务模块中未见第二个路由服务或外挂 router；这是对安装器应用 Python 模块的有界静态结论。安装器还包含 `app/sign/unidbg-sign.jar` 的独立 Java HTTP 签名服务，启动器为其设置单独的 `HG_SIGN_TOKEN` 与可用端口，其接口应单列，不能纳入上述 70 个 FastAPI 路由计数。[app.dis.txt](app.dis.txt:12296)

第三方内容源、付款/授权后端、更新站点与 Java signer 的接口由外呼链路分析另行覆盖。这里没有扫描第三方服务自身的所有未被客户端引用端点，也没有声称它们均可在当前网络或账户条件下成功响应。
