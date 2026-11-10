# 本地 HTTP API 文档

范围：本安装包 `app/server.pyc` 的 **70 个显式 FastAPI 路由**，不是仅从 GUI 的 fetch 字符串拼出的清单。请求签名器与远端平台接口另见总 API 文档及 [REQUEST_CHAIN.md](REQUEST_CHAIN.md)。本次仅静态读取，不调用下载、删除、许可、支付、更新执行等有副作用的接口。

对应可机器解析清单：[local-routes.json](evidence/local-routes.json)。提取器：[extract_local_routes.py](tools/extract_local_routes.py)。它用 xdis 读取字节码，解析顶层 app.get/post/delete 与 MAKE_FUNCTION 的默认值和注解，**不 import/exec 原程序**。每项附 handler 源行及 server.dis.txt 的物理行号。

## 运行地址、安装版可见性与鉴权

服务通常为 `http://127.0.0.1:<PORT>`；server 自身默认 8000，桌面启动器可选择其它端口。**静态注册不等于安装版可访问**：`_PACKAGED_BUILD = bool(LIC._PACKAGED)` 时，中间件仅放行 `/dl`、`/dl/*`、`/img`、`/favicon.ico`；其它路径直接 HTTP 404 `{detail:"not found"}`，早于后续 API key 检查。因此旧 `/search`、`/episodes`、`/video_url`、`/admin`、`/docs` 在打包模式均被隔离。证据 `server.dis.txt:802`、`:6795`（源行 661）。

公共检查按如下顺序执行：

1. 上述打包模式路径过滤。
2. 当 BIND_HOST 为留空/127.0.0.1/localhost 时，非空 Host 必须是 localhost 或 127.0.0.1（可带实际 PORT）；否则 HTTP 403 bad host。
3. `/dl*`、`/admin*`、`/img`、`/stats` 拒绝 Sec-Fetch-Site=cross-site 或非本机 Origin，返回 HTTP 403 cross-site request blocked。
4. 若配置 HG_UI_TOKEN，除了 `/dl` 和 `/dl/status`，`/dl*` 必须具有 cookie `hg_ui_<PORT>` 或 header `x-hg-token`，否则 HTTP 403 unauthorized (open the app window)。cookie 优先。
5. 非豁免、非 admin/stats 路径要求 header `x-api-key` 或 query `api_key`，无效 HTTP 401；每 key 每 60 秒默认 120 次，超过 HTTP 429（RATE_PER_MIN 可配置）。

管理员 API 由 handler 校验 header `x-admin-token` 或 query `admin_token` 与 ADMIN_TOKEN 相等且非空。`/admin` HTML 页面本身没有该校验。`/dl?k=<正确token>` 通过 303 跳转换取 path=/dl、HttpOnly、SameSite=strict cookie；`/dl/status` 不带有效 UI token 只暴露 `{running}`。签名服务 `X-Sign-Token` 与这些 UI/API/admin token 是四套不同用途的凭据。

证据：`server.dis.txt:6112`（UI token）、`:6175`（admin）、`:6232`（Origin）、`:6286`（Host）、`:6620`（跨站）、`:6698`（中间件）、`:23439`（UI cookie）。

## 参数、响应与错误约定

- 下文 Query 表完全来自函数注解与默认值。`必填` 与 `默认 null` 不同。`Request` 是框架注入，不是用户应传的参数。
- 所有正文入口都是 `payload: dict = Body(...)`：**JSON 对象 body 必填**，但没有为内部字段定义 Pydantic BaseModel。字段类型/默认值是 handler 的实际读取、转换与约定，不是额外 schema 强约束；未知字段通常不使用。
- Query/Body 的框架层缺失或类型错误通常是 HTTP 422。每条所列 error 是业务 handler 层；未捕获的底层异常可能 HTTP 500。大多数 `/dl/*` 业务失败仍返回 HTTP 200 + `ok:false`/`error`/`reason`，不要仅以 HTTP 200 判成功。
- 返回字段按实际条件分支列出，不承诺每次同时出现；透传底层对象明确标出未固定 schema，不臆造字段。
- 共同下载设置 body（`/dl/submit`、`/dl/library/update`）：`quality` 允许 1080p/720p/540p/480p/360p，默认或非法值回退 1080p；`series`（兼容 `series_at_once`）默认 2；`episodes`（兼容 `concurrency`）默认 4。两个并发量可转 int 且须在 1–16，bool/转换失败/越界回退各自默认；最后 episodes 不超过 `16 // series`。返回 settings 为 `{quality,series,episodes,workers,max_conn}`，workers=series×episodes、max_conn=16。证据 `server.dis.txt:10015`、`offline_dl.dis.txt:818`、`:2163`、`:43649`。
- **GET 不保证无副作用**：`/download` 提交下载、`/stream` 写媒体缓存、`/dl/diag` 写临时文件、`/dl/license/purchase-poll` 可激活许可，已逐项标注。

## 完整显式路由清单

| # | 方法 | 路径 | handler / 源行 | 安装版 |
|---|---|---|---|---|
| 1 | GET | `/` | `index` / 726 | 404 隔离 |
| 2 | GET | `/stats` | `stats` / 737 | 404 隔离 |
| 3 | GET | `/ui` | `ui` / 757 | 404 隔离 |
| 4 | GET | `/img` | `api_img` / 763 | 按鉴权放行 |
| 5 | GET | `/admin` | `admin_page` / 827 | 404 隔离 |
| 6 | GET | `/admin/keys` | `admin_list_keys` / 833 | 404 隔离 |
| 7 | POST | `/admin/keys` | `admin_gen_key` / 840 | 404 隔离 |
| 8 | POST | `/admin/keys/revoke` | `admin_revoke_key` / 848 | 404 隔离 |
| 9 | DELETE | `/admin/keys` | `admin_delete_key` / 855 | 404 隔离 |
| 10 | GET | `/search` | `api_search` / 862 | 404 隔离 |
| 11 | GET | `/rank` | `api_rank` / 871 | 404 隔离 |
| 12 | GET | `/latest` | `api_latest` / 881 | 404 隔离 |
| 13 | GET | `/filters` | `api_filters` / 900 | 404 隔离 |
| 14 | GET | `/browse` | `api_browse` / 912 | 404 隔离 |
| 15 | GET | `/episodes` | `api_episodes` / 937 | 404 隔离 |
| 16 | POST | `/metrics/batch` | `api_metrics_batch` / 946 | 404 隔离 |
| 17 | GET | `/play` | `api_play` / 967 | 404 隔离 |
| 18 | GET | `/download` | `api_download` / 990 | 404 隔离 |
| 19 | GET | `/download/status` | `api_download_status` / 1000 | 404 隔离 |
| 20 | GET | `/video_url` | `api_video_url` / 1005 | 404 隔离 |
| 21 | GET | `/stream` | `api_stream` / 1021 | 404 隔离 |
| 22 | POST | `/dl/submit` | `dl_submit` / 1204 | 按鉴权放行 |
| 23 | GET | `/dl/search` | `dl_search` / 1286 | 按鉴权放行 |
| 24 | GET | `/dl/search/seasons` | `dl_search_seasons` / 1318 | 按鉴权放行 |
| 25 | GET | `/dl/rank` | `dl_rank` / 1335 | 按鉴权放行 |
| 26 | POST | `/dl/rank-episodes` | `dl_rank_episodes` / 1351 | 按鉴权放行 |
| 27 | GET | `/dl/preview` | `dl_preview` / 1364 | 按鉴权放行 |
| 28 | GET | `/dl/explorer` | `dl_explorer` / 1408 | 按鉴权放行 |
| 29 | GET | `/dl/episodes` | `dl_episodes` / 1437 | 按鉴权放行 |
| 30 | POST | `/dl/resolve` | `dl_resolve` / 1452 | 按鉴权放行 |
| 31 | GET | `/dl/status` | `dl_status` / 1506 | 按鉴权放行 |
| 32 | GET | `/dl/signhealth` | `dl_signhealth` / 1588 | 按鉴权放行 |
| 33 | POST | `/dl/signer-restarted` | `dl_signer_restarted` / 1598 | 按鉴权放行 |
| 34 | GET | `/dl/diag` | `dl_diag` / 1608 | 按鉴权放行 |
| 35 | GET | `/dl/config` | `dl_config_get` / 1727 | 按鉴权放行 |
| 36 | POST | `/dl/config` | `dl_config_set` / 1732 | 按鉴权放行 |
| 37 | POST | `/dl/open` | `dl_open` / 2204 | 按鉴权放行 |
| 38 | POST | `/dl/bugreport` | `dl_bugreport` / 2245 | 按鉴权放行 |
| 39 | POST | `/dl/pick` | `dl_pick` / 2576 | 按鉴权放行 |
| 40 | GET | `/dl/library` | `dl_library` / 2586 | 按鉴权放行 |
| 41 | GET | `/dl/library/episodes` | `dl_library_episodes` / 2594 | 按鉴权放行 |
| 42 | POST | `/dl/library/seen` | `dl_library_seen` / 2606 | 按鉴权放行 |
| 43 | POST | `/dl/library/delete` | `dl_library_delete` / 2623 | 按鉴权放行 |
| 44 | POST | `/dl/library/restore` | `dl_library_restore` / 2649 | 按鉴权放行 |
| 45 | POST | `/dl/library/merge` | `dl_library_merge` / 2663 | 按鉴权放行 |
| 46 | GET | `/dl/library/merge-status` | `dl_library_merge_status` / 2693 | 按鉴权放行 |
| 47 | POST | `/dl/library/convert` | `dl_library_convert` / 2706 | 按鉴权放行 |
| 48 | POST | `/dl/library/convert-cancel` | `dl_library_convert_cancel` / 2759 | 按鉴权放行 |
| 49 | GET | `/dl/library/convert-status` | `dl_library_convert_status` / 2769 | 按鉴权放行 |
| 50 | GET | `/dl/poster` | `dl_poster` / 2775 | 按鉴权放行 |
| 51 | POST | `/dl/library/open` | `dl_library_open` / 2785 | 按鉴权放行 |
| 52 | POST | `/dl/library/play` | `dl_library_play` / 2803 | 按鉴权放行 |
| 53 | GET | `/dl/library/file` | `dl_library_file` / 2842 | 按鉴权放行 |
| 54 | POST | `/dl/library/update` | `dl_library_update` / 2879 | 按鉴权放行 |
| 55 | POST | `/dl/library/seasons/decline` | `dl_library_seasons_decline` / 2901 | 按鉴权放行 |
| 56 | POST | `/dl/cancel` | `dl_cancel` / 2918 | 按鉴权放行 |
| 57 | GET | `/dl` | `dl_page` / 2925 | 按鉴权放行 |
| 58 | GET | `/dl/license/status` | `dl_license_status` / 2945 | 按鉴权放行 |
| 59 | POST | `/dl/license/activate` | `dl_license_activate` / 2950 | 按鉴权放行 |
| 60 | POST | `/dl/license/deactivate` | `dl_license_deactivate` / 2955 | 按鉴权放行 |
| 61 | POST | `/dl/license/reactivate` | `dl_license_reactivate` / 2960 | 按鉴权放行 |
| 62 | GET | `/dl/license/usage` | `dl_license_usage` / 2970 | 按鉴权放行 |
| 63 | GET | `/dl/license/plans` | `dl_license_plans` / 3022 | 按鉴权放行 |
| 64 | POST | `/dl/license/buy` | `dl_license_buy` / 3040 | 按鉴权放行 |
| 65 | GET | `/dl/license/purchase-poll` | `dl_license_purchase_poll` / 3067 | 按鉴权放行 |
| 66 | POST | `/dl/license/manage` | `dl_license_manage` / 3088 | 按鉴权放行 |
| 67 | GET | `/dl/update-check` | `dl_update_check` / 3121 | 按鉴权放行 |
| 68 | POST | `/dl/update-download` | `dl_update_download` / 3161 | 按鉴权放行 |
| 69 | GET | `/dl/update-progress` | `dl_update_progress` / 3239 | 按鉴权放行 |
| 70 | POST | `/dl/update-run` | `dl_update_run` / 3245 | 按鉴权放行 |

## 逐项请求与响应

### 1. GET `/`

实现：`index`，原 `server.py:726`；反汇编 [server.dis.txt:7292](evidence/server.dis.txt#L7292)。

鉴权/可见性：API key 豁免；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{service, ui, endpoints}`，旧 API 索引。

错误：无专门业务错误分支。

行为/副作用：只读。

### 2. GET `/stats`

实现：`stats`，原 `server.py:737`；反汇编 [server.dis.txt:7320](evidence/server.dis.txt#L7320)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{uptime_s, requests, errors, risk, auth_fail, cache_backend, sign_backends, download_tasks}`；每个签名后端含 `{url, ready, pid}` 或 `{url, ready:false, error}`。

错误：管理 token 无效：HTTP 401 `需要 admin_token`。

行为/副作用：读取统计，向每个签名后端 `/` 发健康 GET。

### 3. GET `/ui`

实现：`ui`，原 `server.py:757`；反汇编 [server.dis.txt:7539](evidence/server.dis.txt#L7539)。

鉴权/可见性：API key 豁免；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：HTML：`web/index.html`。

错误：文件缺失为框架/文件层错误。

行为/副作用：只读旧网页。

### 4. GET `/img`

实现：`api_img`，原 `server.py:763`；反汇编 [server.dis.txt:7602](evidence/server.dis.txt#L7602)。

鉴权/可见性：不需 API key/UI token；仍受 Host/跨站和图片白名单限制。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `url` | query | str | 必填 | — |

返回：图片二进制；保留允许的 raster Content-Type，HEIC 可转 JPEG；带 Cache-Control、nosniff、CSP。

错误：HTTP 400 `图片域名不允许`；HTTP 404 `图片读取失败`（含重定向离开白名单、跳转过多、网络/格式错误）。

行为/副作用：访问白名单图片源并缓存；最多 4 轮跳转检查。

### 5. GET `/admin`

实现：`admin_page`，原 `server.py:827`；反汇编 [server.dis.txt:8103](evidence/server.dis.txt#L8103)。

鉴权/可见性：页面本身不校验管理 token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：HTML：`web/admin.html`。

错误：页面本身没有 `_check_admin`；管理操作另行鉴权。

行为/副作用：只读管理网页。

### 6. GET `/admin/keys`

实现：`admin_list_keys`，原 `server.py:833`；反汇编 [server.dis.txt:8166](evidence/server.dis.txt#L8166)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{keys, enabled_count}`；keys 为 KeyStore.list() 的透传列表，内部字段未在 handler 中固定。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：只读本地 API key 存储。

### 7. POST `/admin/keys`

实现：`admin_gen_key`，原 `server.py:840`；反汇编 [server.dis.txt:8219](evidence/server.dis.txt#L8219)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `note` | query | str | `""` | — |

返回：`{ok:true, key, note}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**生成并持久化本地 API key**。`note` 是 query，不是 JSON body。

### 8. POST `/admin/keys/revoke`

实现：`admin_revoke_key`，原 `server.py:848`；反汇编 [server.dis.txt:8276](evidence/server.dis.txt#L8276)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `key` | query | str | 必填 | — |
| `enable` | query | bool | `false` | — |

返回：`{ok: KeyStore.revoke(...) 的结果}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**修改指定 key 的 enabled 状态**；`enable=false` 撤销，`true` 恢复。参数为 query。

### 9. DELETE `/admin/keys`

实现：`admin_delete_key`，原 `server.py:855`；反汇编 [server.dis.txt:8328](evidence/server.dis.txt#L8328)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `key` | query | str | 必填 | — |

返回：`{ok: KeyStore.delete(...) 的结果}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**删除本地 API key**。参数为 query。

### 10. GET `/search`

实现：`api_search`，原 `server.py:862`；反汇编 [server.dis.txt:8377](evidence/server.dis.txt#L8377)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `q` | query | str | 必填 | — |
| `limit` | query | int | `null` | ge=1, le=40 |

返回：`{query, results}`，条目字段见 REQUEST_CHAIN。

错误：HTTP 500 `search失败: ...`。

行为/副作用：调用签名 APP 搜索/缓存。limit 未提供时由 H.search 的环境设置决定，通常 20。

### 11. GET `/rank`

实现：`api_rank`，原 `server.py:871`；反汇编 [server.dis.txt:8451](evidence/server.dis.txt#L8451)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `board` | query | str | `"recommend"` | — |
| `limit` | query | int | `30` | — |

返回：`{board, name, items}`。

错误：未知 board：HTTP 400；上游异常：HTTP 500 `rank失败: ...`。

行为/副作用：读取平台榜单。合法 board 以 H.RANK_BOARDS 为准，索引示例 recommend/hot/new。

### 12. GET `/latest`

实现：`api_latest`，原 `server.py:881`；反汇编 [server.dis.txt:8555](evidence/server.dis.txt#L8555)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `genre` | query | str | `"short_play"` | — |
| `only_today` | query | bool | `true` | — |
| `limit` | query | int | `120` | — |
| `refresh` | query | bool | `false` | — |
| `no_cache` | query | bool | `false` | — |

返回：`{genre, name, mode, only_today, count, items}`；mode 区分今日上新/最新上架等。

错误：未知 genre：HTTP 400；HTTP 500 `latest失败: ...`。

行为/副作用：读取平台最新剧列表；refresh/no_cache 参与刷新选择。genre 常见 short_play/comic_series/ai_series。

### 13. GET `/filters`

实现：`api_filters`，原 `server.py:900`；反汇编 [server.dis.txt:8701](evidence/server.dis.txt#L8701)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `genre` | query | str | `"short_play"` | — |

返回：`{genre, name, rows}`。

错误：未知 genre：HTTP 400；HTTP 500 `filters失败: ...`。

行为/副作用：读取平台分类筛选项。

### 14. GET `/browse`

实现：`api_browse`，原 `server.py:912`；反汇编 [server.dis.txt:8806](evidence/server.dis.txt#L8806)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `genre` | query | str | `"ai_series"` | — |
| `theme` | query | str | `null` | — |
| `setting` | query | str | `null` | — |
| `background` | query | str | `null` | — |
| `sort` | query | str | `"online_time"` | — |
| `gender` | query | str | `null` | — |
| `days` | query | str | `null` | — |
| `status` | query | str | `null` | — |
| `limit` | query | int | `60` | — |

返回：`{genre, name, count, note, items}`；每条补 `stream_url` 和 `episodes_url`。

错误：未知 genre：HTTP 400；HTTP 500 `browse失败: ...`。

行为/副作用：读取平台筛选目录。theme/setting/background 可为逗号分隔文本，经本地 `_csv` 处理。

### 15. GET `/episodes`

实现：`api_episodes`，原 `server.py:937`；反汇编 [server.dis.txt:9007](evidence/server.dis.txt#L9007)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | 必填 | — |

返回：`{meta, episodes}`，完整剧信息与每集模型，见 REQUEST_CHAIN。

错误：HTTP 500 `episodes失败: ...`。

行为/副作用：读取 APP 剧详情/缓存。

### 16. POST `/metrics/batch`

实现：`api_metrics_batch`，原 `server.py:946`；反汇编 [server.dis.txt:9085](evidence/server.dis.txt#L9085)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list 或逗号分隔 str`；也兼容 `series_id`；必需得到非空 ID 集合，最多 200。`batch_size: 可转 int=20`，有效批大小限制 1–20。

返回：`{count, items, failed, batch_size}`。

错误：空 ID 或超过 200：HTTP 400；平台查询异常：HTTP 500 `metrics batch失败`。body 内类型不受 Pydantic 字段模型约束，转换失败可能成为 500。

行为/副作用：批量读取剧详情指标。

### 17. GET `/play`

实现：`api_play`，原 `server.py:967`；反汇编 [server.dis.txt:9298](evidence/server.dis.txt#L9298)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | 必填 | — |
| `ep` | query | str | `"all"` | — |

返回：`{series_id, title, note, episodes}`；集条目 `{index, vid, title, duration, encrypted_url, backup, size, definition, stream_url}`。note 明示 encrypted_url 是 CENC 密文地址。

错误：HTTP 500 `play失败: ...`。

行为/副作用：查询详情与视频模型；ep 支持 all 或集数范围。返回可播放路径 `/stream?vid=...` 与远端密文 URL，不在本接口写媒体。

### 18. GET `/download`

实现：`api_download`，原 `server.py:990`；反汇编 [server.dis.txt:9515](evidence/server.dis.txt#L9515)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | 必填 | — |
| `ep` | query | str | `"all"` | — |
| `ep_covers` | query | bool | `false` | — |

返回：`{task_id, status_url}`。

错误：HTTP 500 `download失败: ...`。

行为/副作用：**即使是 GET 也会提交下载任务并写文件**；`ep` 支持 all/范围，`ep_covers` 控制集封面。

### 19. GET `/download/status`

实现：`api_download_status`，原 `server.py:1000`；反汇编 [server.dis.txt:9602](evidence/server.dis.txt#L9602)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `task_id` | query | str | `null` | — |

返回：H.manager().status(task_id) 的透传结果；具体任务状态 schema 未在 handler 定义。

错误：未在 handler 显式捕获错误。

行为/副作用：只读任务状态。

### 20. GET `/video_url`

实现：`api_video_url`，原 `server.py:1005`；反汇编 [server.dis.txt:9635](evidence/server.dis.txt#L9635)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `vid` | query | str | 必填 | — |

返回：`{vid, url, backup, size, definition}`。

错误：没有 URL：HTTP 404 `无直链`；其它异常：HTTP 500 `video_url失败`。

行为/副作用：查询视频模型/缓存，URL 可能是加密媒体，不等于可直接播放文件。

### 21. GET `/stream`

实现：`api_stream`，原 `server.py:1021`；反汇编 [server.dis.txt:9776](evidence/server.dis.txt#L9776)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | `null` | — |
| `ep` | query | str | `"1"` | — |
| `vid` | query | str | `null` | — |
| `quality` | query | str | `"best"` | — |

返回：`video/mp4` FileResponse；Content-Disposition inline，UTF-8 文件名。

错误：缺 series_id 和 vid：HTTP 400；找不到集号：HTTP 404；其它：HTTP 500 `stream失败`。

行为/副作用：**GET 会按需下载、生成解密缓存，再读本地文件**。vid 优先；否则用 series_id+ep；非数字 ep 回退第 1 集。

### 22. POST `/dl/submit`

实现：`dl_submit`，原 `server.py:1204`；反汇编 [server.dis.txt:11345](evidence/server.dis.txt#L11345)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`text: str=""`；`series_ids: list=[]`；`ranges: object={}`；`scores: object={}`；下载设置见公共 body 说明。

返回：成功 `{ok:true, settings}`；部分许可受限另加 `blocked, need_license, free_limit, free_used`；全部受限 `{ok:false, reason, blocked, free_limit, free_used}`。

错误：业务 JSON `{ok:false,error}`：queue is empty、已有下载运行；许可失败由 reason/blocked 表示。

行为/副作用：**启动后台下载/写文件**，清理 live 状态、取消标记，执行许可检查。

### 23. GET `/dl/search`

实现：`dl_search`，原 `server.py:1286`；反汇编 [server.dis.txt:12031](evidence/server.dis.txt#L12031)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `q` | query | str | `""` | — |
| `cursor` | query | str | `""` | — |
| `again` | query | int | `0` | — |

返回：空 q：`{results:[]}`；正常 `{query, results, cursor, pending, backup, slow}` 并合并系列条带字段；分页 `{query,results,cursor,expired}`。

错误：过长搜索 `{query,results:[],error}`；无效游标 `expired:true`；异常 `{results:[],error}`，业务失败一般仍 HTTP 200。

行为/副作用：异步远端搜索、缓存及网页回退；again=1 表示重新询问任务。

### 24. GET `/dl/search/seasons`

实现：`dl_search_seasons`，原 `server.py:1318`；反汇编 [server.dis.txt:12321](evidence/server.dis.txt#L12321)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `q` | query | str | `""` | — |

返回：`{series, related, complete, extra}`，可附 query、backup；具体条带字段来自 `_search_strip`。

错误：异常在上述结构附 `error`，complete=false；空/过长 q 返回空结果。

行为/副作用：查询/补全搜索关联续季信息。

### 25. GET `/dl/rank`

实现：`dl_rank`，原 `server.py:1335`；反汇编 [server.dis.txt:12486](evidence/server.dis.txt#L12486)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `board` | query | str | `"recommend"` | — |
| `category` | query | str | `"all"` | — |
| `offset` | query | int | `0` | — |
| `size` | query | int | `100` | — |

返回：`{results,has_more:false,next_offset:0}`。

错误：异常同结构附 `error`。

行为/副作用：读取 ODL.hgdj_rank(category) 的网页榜单；category 仅 ai/human/comic，非法值回退 ai。**board/offset/size 虽声明但此 handler 不使用**。

### 26. POST `/dl/rank-episodes`

实现：`dl_rank_episodes`，原 `server.py:1351`；反汇编 [server.dis.txt:12596](evidence/server.dis.txt#L12596)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list=[]`；不是 list 则按空列表处理，最多传前 120 个。

返回：`{eps: ODL.hgdj_episodes(...) 的结果}`。

错误：异常 `{eps:{},error}`。

行为/副作用：读取网页集数信息。

### 27. GET `/dl/preview`

实现：`dl_preview`，原 `server.py:1364`；反汇编 [server.dis.txt:12709](evidence/server.dis.txt#L12709)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | `""` | — |
| `ep` | query | int | `1` | — |
| `fresh` | query | int | `0` | — |

返回：透传 ODL.hgdj_preview：成功 `{ok,series_id,title,episode_cnt,free,ep,url,poster,duration,width,height}`；具体字段随返回分支。

错误：`{ok:false,error}`，可为 network/unavailable/locked。

行为/副作用：只查询公开网页预览地址；受 accessible_episode_cnt 限制。fresh 被转为 bool。

### 28. GET `/dl/explorer`

实现：`dl_explorer`，原 `server.py:1408`；反汇编 [server.dis.txt:13045](evidence/server.dis.txt#L13045)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `page` | query | int | `1` | — |
| `size` | query | int | `18` | — |

返回：`{results,page,pages,total,size}`。

错误：未显式捕获转换异常；内部目录不可用行为由 `_explorer_catalog` 决定。

行为/副作用：读取/缓存 explorer 目录，page 至少 1，size 1–60，默认 18。

### 29. GET `/dl/episodes`

实现：`dl_episodes`，原 `server.py:1437`；反汇编 [server.dis.txt:13278](evidence/server.dis.txt#L13278)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | `""` | — |

返回：`{series_id,title,cover,total,episodes}`，episodes 是排序去重的集序号，不是完整集对象。

错误：缺 ID `{episodes:[],error:"no series_id"}`；异常 `{episodes:[],error}`。

行为/副作用：查询剧详情/缓存。

### 30. POST `/dl/resolve`

实现：`dl_resolve`，原 `server.py:1452`；反汇编 [server.dis.txt:13425](evidence/server.dis.txt#L13425)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`text: str=""`，分享链接或多行分享文本。

返回：`{resolved:[...]}`；成功条目 `{series_id,title,total,cover}`；busy 条目含 `error,busy`；不可用条目含 `hg_id,error,unavailable`；未识别含 `error:"unresolved"`。

错误：单个解析错误放在 resolved 条目；handler 自身未统一 catch。

行为/副作用：并发解析分享链接/榜单，最多 8 worker；可能访问远端网页。

### 31. GET `/dl/status`

实现：`dl_status`，原 `server.py:1506`；反汇编 [server.dis.txt:13572](evidence/server.dis.txt#L13572)。

鉴权/可见性：UI token 可选；无 token 仅返回 running。

声明参数：无（Request 若存在由框架注入）。

返回：没有 UI token 仅 `{running:bool}`。有 token 返回 `{running,started,mode,series,log}` 加速率/字节/活动数/集计数/settings/source；library 模式还含 phase/checked/to_check/found/unread/seasons。

错误：本接口是 UI token 豁免项，未授权不会收到完整日志/路径。

行为/副作用：只读任务与实时进度，部分异常回退快照。

### 32. GET `/dl/signhealth`

实现：`dl_signhealth`，原 `server.py:1588`；反汇编 [server.dis.txt:14172](evidence/server.dis.txt#L14172)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,fail}`，H.sign_stats()。

错误：无专门捕获分支。

行为/副作用：只读签名成功/失败计数。

### 33. POST `/dl/signer-restarted`

实现：`dl_signer_restarted`，原 `server.py:1598`；反汇编 [server.dis.txt:14212](evidence/server.dis.txt#L14212)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：无专门捕获分支。

行为/副作用：**改变签名器冷启动状态并启动后台预热**。此接口是“通知已重启”，不是直接杀进程。

### 34. GET `/dl/diag`

实现：`dl_diag`，原 `server.py:1608`；反汇编 [server.dis.txt:14251](evidence/server.dis.txt#L14251)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{pid,web_port,bind_host,sign_server,signer_healthy,output_dir,output_writable,output_write_error,state_dir,data_dir,python,tls_trust,running,mode,app_log,dl_log}`。

错误：可写测试错误写入 output_write_error；签名测试异常写为不健康。

行为/副作用：**GET 也会创建输出目录、写入并删除 .hg_write_test、调用签名探测**；读取日志。

### 35. GET `/dl/config`

实现：`dl_config_get`，原 `server.py:1727`；反汇编 [server.dis.txt:15273](evidence/server.dis.txt#L15273)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{output_dir}`。

错误：无专门捕获分支。

行为/副作用：只读下载输出目录。

### 36. POST `/dl/config`

实现：`dl_config_set`，原 `server.py:1732`；反汇编 [server.dis.txt:15298](evidence/server.dis.txt#L15298)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`output_dir: str=""`。

返回：成功 `{ok:true,output_dir}`。

错误：失败 `{ok:false,error,output_dir}`。

行为/副作用：**修改下载输出目录并持久化 dlconfig.json**。

### 37. POST `/dl/open`

实现：`dl_open`，原 `server.py:2204`；反汇编 [server.dis.txt:18487](evidence/server.dis.txt#L18487)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,output_dir}`。

错误：`{ok:false,error,output_dir}`。

行为/副作用：**创建输出目录并打开系统文件管理器**。

### 38. POST `/dl/bugreport`

实现：`dl_bugreport`，原 `server.py:2245`；反汇编 [server.dis.txt:18849](evidence/server.dis.txt#L18849)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`logs: bool=true`，`screenshot: bool=false`，均经 bool()。

返回：`{ok:true,path,included}`，本地 bugreport ZIP。

错误：`{ok:false,error}`；截图失败可写入 ZIP 内 screenshot-FAILED.txt。

行为/副作用：**写日志 ZIP，可截图并打开文件管理器定位文件**；该 handler 没有自动上传报告。

### 39. POST `/dl/pick`

实现：`dl_pick`，原 `server.py:2576`；反汇编 [server.dis.txt:20727](evidence/server.dis.txt#L20727)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：Windows 原生目录选择器结果（通常 `{ok,path}`，其它错误键来自 `_pick_folder`）。

错误：非 Windows `{ok:false,error:"folder picker is Windows-only here — type the path instead"}`。

行为/副作用：**打开系统选目录对话框/子进程**；不自动提交配置。

### 40. GET `/dl/library`

实现：`dl_library`，原 `server.py:2586`；反汇编 [server.dis.txt:20789](evidence/server.dis.txt#L20789)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{items,root}`；item 含 `{name,series_id,title,local,total,new,fresh,score,updated,size,poster,cover,h264}`。底层证据 `offline_dl.dis.txt:18670`。

错误：扫描异常 `{items:[],error}`。

行为/副作用：**扫描本地下载库，seen_at 尚无有效值时可写入已看时间基线**；不发起媒体下载。

### 41. GET `/dl/library/episodes`

实现：`dl_library_episodes`，原 `server.py:2594`；反汇编 [server.dis.txt:20857](evidence/server.dis.txt#L20857)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |

返回：`{name,title,total,downloaded,fresh,episodes,h264}`；episodes 条目为 `{index,fresh}`。底层证据 `offline_dl.dis.txt:19081`（源行 2119、2132）。

错误：不安全/空目录名，或目录不存在：HTTP 404 `series not found`。

行为/副作用：只读本地剧目录。

### 42. POST `/dl/library/seen`

实现：`dl_library_seen`，原 `server.py:2606`；反汇编 [server.dis.txt:20924](evidence/server.dis.txt#L20924)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list` 可批量；否则 `name: str=""`。

返回：批量 `{ok:true,count}`；单项 `{ok:bool}`。

错误：无效名不标记；未设置统一异常捕获。

行为/副作用：**持久化已看/已知状态**。

### 43. POST `/dl/library/delete`

实现：`dl_library_delete`，原 `server.py:2623`；反汇编 [server.dis.txt:21048](evidence/server.dis.txt#L21048)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list=[]`，逐个名称清理/校验。

返回：ODL.library_delete 结果，含 `{ok,moved,errors}`；moved 条目含恢复 token。

错误：异常 `{ok:false,moved:[],errors:{"*":错误}}`；如果移动结果不属于用户请求，自动恢复并记 `not the series asked for (left in place)`。

行为/副作用：**将所选库目录移入可恢复位置**；接口名 delete 不等于立即永久擦除。

### 44. POST `/dl/library/restore`

实现：`dl_library_restore`，原 `server.py:2649`；反汇编 [server.dis.txt:21296](evidence/server.dis.txt#L21296)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`token: str=""`，由 delete 返回。

返回：`{ok:true,name}`，透传 ODL.library_restore。底层证据 `offline_dl.dis.txt:19873`。

错误：`{ok:false,error}`：not in trash、已有同名剧目录、文件操作失败。

行为/副作用：**将 .trash 下之前移走的库目录恢复到输出根目录**。

### 45. POST `/dl/library/merge`

实现：`dl_library_merge`，原 `server.py:2663`；反汇编 [server.dis.txt:21380](evidence/server.dis.txt#L21380)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`variant: str="original"`，只允许 original/h264，否则回退 original。

返回：`{ok:true,started:true}`；进度另查 merge-status。

错误：无名称 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`。

行为/副作用：**后台合并剧集并写合并媒体**，状态含 variant。

### 46. GET `/dl/library/merge-status`

实现：`dl_library_merge_status`，原 `server.py:2693`；反汇编 [server.dis.txt:21577](evidence/server.dis.txt#L21577)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{running,name,pct,file,error,done,variant}`，合并状态副本。

错误：无专门错误分支。

行为/副作用：只读。

### 47. POST `/dl/library/convert`

实现：`dl_library_convert`，原 `server.py:2706`；反汇编 [server.dis.txt:21603](evidence/server.dis.txt#L21603)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list` 或 `name`；`keep_original: bool=true`；`mode: str="auto"`（auto/gpu/cpu）；`speed: str="quality"`（quality/balanced/fast）；`threads: 可转int=0`，限制 0–64。

返回：`{ok:true,started:true}`；进度另查 convert-status。

错误：无剧名 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`；无效 mode/speed 回退默认。

行为/副作用：**后台转码写 H264 文件**；keep_original 传入转换流程，涉及原文件保留策略。

### 48. POST `/dl/library/convert-cancel`

实现：`dl_library_convert_cancel`，原 `server.py:2759`；反汇编 [server.dis.txt:21942](evidence/server.dis.txt#L21942)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：异常 `{ok:false,error}`。

行为/副作用：**请求取消转码**。

### 49. GET `/dl/library/convert-status`

实现：`dl_library_convert_status`，原 `server.py:2769`；反汇编 [server.dis.txt:22020](evidence/server.dis.txt#L22020)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{running,name,pct,encoder,mode,speed,total,series_done,converted,skipped,failed,error,done}`。

错误：无专门错误分支。

行为/副作用：只读转码状态。

### 50. GET `/dl/poster`

实现：`dl_poster`，原 `server.py:2775`；反汇编 [server.dis.txt:22046](evidence/server.dis.txt#L22046)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |

返回：`image/jpeg` FileResponse，读取所选目录 poster.jpg，Cache-Control max-age=3600。

错误：HTTP 404 `no poster`。

行为/副作用：只读本地海报。

### 51. POST `/dl/library/open`

实现：`dl_library_open`，原 `server.py:2785`；反汇编 [server.dis.txt:22132](evidence/server.dis.txt#L22132)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`sub: str=""`（如 H264），经 `_safe_series_name` 校验。

返回：`{ok:true}`。

错误：`{ok:false,error}`：folder not found/no converted files yet/系统异常。

行为/副作用：**打开所选剧目录或子目录**。

### 52. POST `/dl/library/play`

实现：`dl_library_play`，原 `server.py:2803`；反汇编 [server.dis.txt:22309](evidence/server.dis.txt#L22309)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`ep: 可转int/未提供=null`，内部从本地 MP4 文件名解析序号；省略、无法转 int 或未找到集号时，回退到按序号排序的第一个本地 MP4。

返回：`{ok:true,file}`。

错误：`{ok:false,error}`：folder not found/no episodes downloaded yet/系统异常。

行为/副作用：**在系统默认播放器打开本地集文件**；Windows startfile，macOS open，其它 xdg-open。

### 53. GET `/dl/library/file`

实现：`dl_library_file`，原 `server.py:2842`；反汇编 [server.dis.txt:22670](evidence/server.dis.txt#L22670)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |
| `ep` | query | int | `0` | — |

返回：`video/mp4` FileResponse，Cache-Control no-store；优先找 第NNN集.mp4，随后按 MP4 文件名内数字匹配。

错误：HTTP 404 `series not found` / `episode not found`。

行为/副作用：只读取所选库内媒体，安全名称校验。

### 54. POST `/dl/library/update`

实现：`dl_library_update`，原 `server.py:2879`；反汇编 [server.dis.txt:23075](evidence/server.dis.txt#L23075)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list/未提供`；下载设置见公共 body；未提供名称时可交底层进行库更新，明确给出的名称需合法。

返回：`{ok:true,settings}`。

错误：`{ok:false,error}`：invalid series name(s)、已有 download/update 运行。

行为/副作用：**后台检查库更新并下载缺集，写文件**，与主下载队列互斥。

### 55. POST `/dl/library/seasons/decline`

实现：`dl_library_seasons_decline`，原 `server.py:2901`；反汇编 [server.dis.txt:23278](evidence/server.dis.txt#L23278)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list=[]`，最多检查前 200 个，ID 必须匹配 15–20 位十进制。

返回：`{ok:true,declined}`。

错误：`{ok:false,error:"no series ids"}`。

行为/副作用：**记录拒绝的续季提示状态**。

### 56. POST `/dl/cancel`

实现：`dl_cancel`，原 `server.py:2918`；反汇编 [server.dis.txt:23398](evidence/server.dis.txt#L23398)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：无专门错误分支。

行为/副作用：**设置取消下载标志**；日志说明完成已在途集，不再启动新集。

### 57. GET `/dl`

实现：`dl_page`，原 `server.py:2925`；反汇编 [server.dis.txt:23439](evidence/server.dis.txt#L23439)。

鉴权/可见性：UI bootstrap；不要求已有 UI token。

声明参数：无（Request 若存在由框架注入）。

另从 request.query_params 读取 `k: str=""`，它不在函数签名中。

返回：若 query `k` 与 HG_UI_TOKEN 匹配：303 跳转 `/dl` 并设置 token cookie；否则返回 web/downloader.html，Cache-Control no-store。

错误：token 不匹配不会建立会话；页面可显示，受保护 API 仍拒绝。

行为/副作用：成功 bootstrap 时**设置 HttpOnly、SameSite=strict、path=/dl 的 UI cookie**。

### 58. GET `/dl/license/status`

实现：`dl_license_status`，原 `server.py:2945`；反汇编 [server.dis.txt:23561](evidence/server.dis.txt#L23561)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.status() 透传对象；handler 未声明固定 schema（许可模块接口参见远端 API 文档）。

错误：未统一捕获 LIC.status 异常。

行为/副作用：读取许可状态，底层可能刷新缓存。

### 59. POST `/dl/license/activate`

实现：`dl_license_activate`，原 `server.py:2950`；反汇编 [server.dis.txt:23585](evidence/server.dis.txt#L23585)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`key: str=""`。

返回：LIC.activate(key) 透传许可结果；字段由许可模块决定。

错误：失败 reason/错误由 LIC.activate 决定；handler 无统一 catch。

行为/副作用：**尝试激活许可并更新本机许可状态**。

### 60. POST `/dl/license/deactivate`

实现：`dl_license_deactivate`，原 `server.py:2955`；反汇编 [server.dis.txt:23624](evidence/server.dis.txt#L23624)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.deactivate() 透传结果。

错误：错误由许可模块决定。

行为/副作用：**解绑/停用本机许可**。

### 61. POST `/dl/license/reactivate`

实现：`dl_license_reactivate`，原 `server.py:2960`；反汇编 [server.dis.txt:23648](evidence/server.dis.txt#L23648)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：有 current_key 时透传 LIC.activate(current_key)。

错误：无 key：`{ok:false,reason:"no_key"}`。

行为/副作用：**使用已保存 key 重新激活**。

### 62. GET `/dl/license/usage`

实现：`dl_license_usage`，原 `server.py:2970`；反汇编 [server.dis.txt:23698](evidence/server.dis.txt#L23698)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.usage() 透传统计；handler 未固定字段。

错误：错误由许可模块决定。

行为/副作用：读取许可用量。

### 63. GET `/dl/license/plans`

实现：`dl_license_plans`，原 `server.py:3022`；反汇编 [server.dis.txt:24002](evidence/server.dis.txt#L24002)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：支付服务 GET /plans 的 JSON 透传，缓存 600 秒。

错误：`{plans:[],error:"unavailable"}`。

行为/副作用：网络读取方案/更新缓存。

### 64. POST `/dl/license/buy`

实现：`dl_license_buy`，原 `server.py:3040`；反汇编 [server.dis.txt:24137](evidence/server.dis.txt#L24137)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`plan: str=""`，只允许 month/year/life。

返回：`{ok:true,session_id,url}`。

错误：`{ok:false,reason}`：bad_plan/no_session/bad_checkout_url；网络失败另有 detail（截断 200 字）。

行为/副作用：**创建结账会话并打开浏览器支付页**；不是已完成付款。

### 65. GET `/dl/license/purchase-poll`

实现：`dl_license_purchase_poll`，原 `server.py:3067`；反汇编 [server.dis.txt:24374](evidence/server.dis.txt#L24374)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `session_id` | query | str | `""` | — |

返回：pending 分支 `{pending:true,reason}`；拿到 key 后返回 `{pending:false,ok,activated,reason,usage}`。

错误：缺 session `{pending:false,ok:false,reason:"no_session"}`；网络 pending=true,reason=network；未就绪 reason=not_ready 或服务端 reason。

行为/副作用：**GET 若取回 key 会自动调用 LIC.activate**，并非严格只读。

### 66. POST `/dl/license/manage`

实现：`dl_license_manage`，原 `server.py:3088`；反汇编 [server.dis.txt:24562](evidence/server.dis.txt#L24562)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,url}`。

错误：`{ok:false,reason}`：no_key/unavailable/bad_portal_url；网络失败附 detail。

行为/副作用：**用当前 key/device 创建管理门户并打开浏览器**。

### 67. GET `/dl/update-check`

实现：`dl_update_check`，原 `server.py:3121`；反汇编 [server.dis.txt:24822](evidence/server.dis.txt#L24822)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,current,latest,update,url,page,name,notes}`；失败/无可用结果 `{ok:false,current,update:false}`。

错误：网络等异常转上述失败结构；说明 notes 最多 800 字。

行为/副作用：GET GitHub latest release，缓存 1800 秒；不下载安装包。

### 68. POST `/dl/update-download`

实现：`dl_update_download`，原 `server.py:3161`；反汇编 [server.dis.txt:25200](evidence/server.dis.txt#L25200)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,path,name,sha256,signed,valid,publisher,expected_publisher,trusted}`。

错误：busy `{ok:false,busy:true,error}`；无可信下载 URL/下载失败 `{ok:false,error}`。

行为/副作用：**下载 exe 到本地 update 目录、计算 SHA-256、调用 PowerShell Authenticode 检验**；仅允许预期 GitHub release 路径，不在此 handler 执行。

### 69. GET `/dl/update-progress`

实现：`dl_update_progress`，原 `server.py:3239`；反汇编 [server.dis.txt:25972](evidence/server.dis.txt#L25972)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,state,pct,downloaded,total,error}`。state 可 idle/starting/downloading/verifying/done/error。

错误：无专门错误分支。

行为/副作用：只读更新下载进度。

### 70. POST `/dl/update-run`

实现：`dl_update_run`，原 `server.py:3245`；反汇编 [server.dis.txt:26004](evidence/server.dis.txt#L26004)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`path: str=""`，必须是本进程已下载记录对应 exe。

返回：`{ok:true}`。

错误：`{ok:false,error}`：unknown download、非 exe、无校验记录、SHA-256 改变、无法验签、预期发布者校验未通过。

行为/副作用：**经路径/记录/hash/发布者检查后使用 os.startfile 执行安装程序**。

## 框架自动路由与没有注册的路径

`server.py` 以 `FastAPI(title="红果短剧 API", version="1.0")` 初始化，未传 docs_url、redoc_url、openapi_url 开关（`server.dis.txt:956`）。已从安装器提取并校验 **FastAPI 0.141.1** 源码：其 [applications.py:1105](extracted/python/Lib/site-packages/fastapi/applications.py#L1105) setup 确定增加下列 4 条框架路径；[Starlette routing.py:224](extracted/python/Lib/site-packages/starlette/routing.py#L224) 的 Route 默认 GET 且追加 HEAD。因此是 **70 条显式 method/path + 8 条框架 method/path = 78 条组合**，框架路由机器表见 [framework-routes.json](evidence/framework-routes.json)。

| 方法 | 路径 | 请求参数 | 返回 | 非安装模式鉴权 | 副作用 |
|---|---|---|---|---|---|
| GET / HEAD | `/openapi.json` | 无业务参数，Request 注入 | OpenAPI JSON（HEAD 无 body） | API key 豁免 | 生成/缓存 schema |
| GET / HEAD | `/docs` | 无业务参数，Request 注入 | Swagger UI HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |
| GET / HEAD | `/docs/oauth2-redirect` | 框架 OAuth redirect 页面，参数由其 JS 使用，业务 server 未声明 | OAuth redirect HTML（HEAD 无 body） | **不在豁免清单，需 API key** | 浏览器 OAuth 回跳处理 |
| GET / HEAD | `/redoc` | 无业务参数，Request 注入 | ReDoc HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |

安装模式中，上述四条路径均先被过滤返回 404；非安装模式中的中间件错误（Host、401、429）仍按本文公共规则。HEAD 的自动补充仅在上述 Starlette Route 确认，不额外将 70 条 app.get 业务路由都臆计为支持 HEAD。

`/favicon.ico` 在中间件放行及 API key 豁免清单，但 **没有找到显式 handler 注册**；不要将其当作已实现的图片接口。没有发现本业务模块的动态 add_api_route/include_router/mount 追加路由。

## 与前端请求交叉核对及可复现性

提取的 `app/web/downloader.html`、`index.html`、`admin.html` 中页面请求用于交叉验证：桌面页使用 `/dl/*` 与 `/img`；旧页面使用 `/search`、`/rank`、`/latest`、`/filters`、`/browse`、`/episodes`、`/play`、`/download` 等；管理页面使用 `/admin/keys`、`/admin/keys/revoke`。证据 [index.html:59](extracted/app/web/index.html#L59)、[admin.html:47](extracted/app/web/admin.html#L47)、[downloader.inline.js:372](evidence/downloader.inline.js#L372)。外部 explorer 域名请求不应误计为本地注册路由。

该清单按程序声明完整覆盖 70 条 method+path 组合，`GET /admin/keys`、`POST /admin/keys`、`DELETE /admin/keys` 与 `GET/POST /dl/config` 分别计数。当前没有运行原 server，也没有通过调用写接口来猜返回值；需验证的动态环境行为与透传模块扩展字段均保留为明确边界。
