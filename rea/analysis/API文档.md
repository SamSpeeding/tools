# HongguoDownloader API 文档

对象：`HongguoDownloader-Setup.exe`，版本 **1.0.0.72**。整理日期：2026-10-12。

本文整理该安装包业务层可恢复的全部 HTTP 接口，覆盖本地 FastAPI 路由、本地签名器、APP 平台、公开网页、目录服务、许可证、支付和更新调用。每个接口尽可能标出方法、参数、响应、鉴权、调用关系和代码证据；动态字段与尚未运行验证的行为单独说明。

## 阅读入口

- [一、本地服务接口](#local-api)：**70 个业务层明确注册的 method/path**，GET 40、POST 29、DELETE 1；另有 FastAPI 自动生成的 4 个文档路径，各支持 GET/HEAD。安装版路径过滤允许50个业务接口，屏蔽其余20个以及4个框架文档路径。允许通过路径过滤不等于满足令牌或许可证条件。
- [二、本地签名服务](#signer-api)：Jar 注册的 `/sign`，本次已运行验证。
- [三、外部服务接口](#remote-api)：**33 个出站路径／模板**，包含 8 个不同的 APP 业务路径，以及网页、目录、许可证、支付、更新和兼容签名服务调用。这是客户端使用到的接口范围，不代表远端服务的全部接口。
- [四、视频加密与下载后处理](#video-encryption)：原程序如何从加密 MP4 得到最终文件，以及当前导出脚本的能力边界。
- [搜索至全剧地址的详细流程](REQUEST_CHAIN.md)。

### 已实测范围

本次重写脚本在 Mac ARM64 上成功启动提取出的 Java 签名器。关键词“逆袭”选中 `series_id=7689391720735181848` 后，成功取得 **111/111 集地址、555 条清晰度记录**；25 个平台请求与25个签名请求均 HTTP 200。第 1、56、111 集的 CDN 链接各读128字节，均 HTTP206 且为MP4文件头。

测试样本的全部 555 条清晰度记录均为 `encrypt_info.encrypt=true`、`encryption_method="cenc-aes-ctr"`，下载URL有有效期。该结果证明本次样本的目录、地址覆盖率及抽查链接可读性。主导出脚本没有执行解密；随后已另行完成《坠崖捡个参娃娃》第 1 集的下载、解密、重封装和完整音视频解码验证，详见第四部分，不能把单集结果外推为所有剧集已验证。

其余接口按字节码和界面代码静态还原；支付、许可激活、文件删除、安装更新等接口没有为编写文档而触发。本地原 FastAPI 服务和 Windows EXE 未运行，不能把静态路由信息写成其运行抓包结果。

### 证据与复核

- 安装包 SHA-256：`9d77a2548cc1bde92c4a269a3f482655b4f5fc538421f328af8d959d6739b592`。
- [REA 完整证据](evidence/rea-evidence.json)：安装包 artifact inspection、提取网页 JavaScript 静态分析，4 条保留记录。
- Python 3.11 字节码用 xdis 静态反汇编；Java 用 javap 检查。未将辅助工具输出冒充 REA 原生 Python 反编译能力。
- [本地路由清单](evidence/local-routes.json)、[独立枚举与鉴权审计](evidence/api-audit.md)、[外部接口清单](evidence/remote-routes.json)。
- [本次50条请求记录](../outputs/requests.jsonl)、[CDN抽查结果](evidence/live-verification.json)、[完整剧信息及地址](../outputs/逆袭111集.json)。

文中 `*.dis.txt:行号` 指已保存反汇编文本的物理行号，`源行` 指 pyc 中携带的原源码行号；这两者不是同一套行号。接口成功通常还要求业务状态码成功，HTTP200本身不足以判定。

<a id="local-api"></a>

## 一、本地服务接口

范围：本安装包 `app/server.pyc` 的 **70 个显式 FastAPI 路由**，不是仅从 GUI 的 fetch 字符串拼出的清单。请求签名器与远端平台接口另见总 API 文档及 [REQUEST_CHAIN.md](REQUEST_CHAIN.md)。本次仅静态读取，不调用下载、删除、许可、支付、更新执行等有副作用的接口。

对应可机器解析清单：[local-routes.json](evidence/local-routes.json)。提取器：[extract_local_routes.py](tools/extract_local_routes.py)。它用 xdis 读取字节码，解析顶层 app.get/post/delete 与 MAKE_FUNCTION 的默认值和注解，**不 import/exec 原程序**。每项附 handler 源行及 server.dis.txt 的物理行号。

### 运行地址、安装版可见性与鉴权

服务通常为 `http://127.0.0.1:<PORT>`；server 自身默认 8000，桌面启动器可选择其它端口。**静态注册不等于安装版可访问**：`_PACKAGED_BUILD = bool(LIC._PACKAGED)` 时，中间件仅放行 `/dl`、`/dl/*`、`/img`、`/favicon.ico`；其它路径直接 HTTP 404 `{detail:"not found"}`，早于后续 API key 检查。因此旧 `/search`、`/episodes`、`/video_url`、`/admin`、`/docs` 在打包模式均被隔离。证据 `server.dis.txt:802`、`:6795`（源行 661）。

公共检查按如下顺序执行：

1. 上述打包模式路径过滤。
2. 当 BIND_HOST 为留空/127.0.0.1/localhost 时，非空 Host 必须是 localhost 或 127.0.0.1（可带实际 PORT）；否则 HTTP 403 bad host。
3. `/dl*`、`/admin*`、`/img`、`/stats` 拒绝 Sec-Fetch-Site=cross-site 或非本机 Origin，返回 HTTP 403 cross-site request blocked。
4. 若配置 HG_UI_TOKEN，除了 `/dl` 和 `/dl/status`，`/dl*` 必须具有 cookie `hg_ui_<PORT>` 或 header `x-hg-token`，否则 HTTP 403 unauthorized (open the app window)。cookie 优先。
5. 非豁免、非 admin/stats 路径要求 header `x-api-key` 或 query `api_key`，无效 HTTP 401；每 key 每 60 秒默认 120 次，超过 HTTP 429（RATE_PER_MIN 可配置）。

管理员 API 由 handler 校验 header `x-admin-token` 或 query `admin_token` 与 ADMIN_TOKEN 相等且非空。`/admin` HTML 页面本身没有该校验。`/dl?k=<正确token>` 通过 303 跳转换取 path=/dl、HttpOnly、SameSite=strict cookie；`/dl/status` 不带有效 UI token 只暴露 `{running}`。签名服务 `X-Sign-Token` 与这些 UI/API/admin token 是四套不同用途的凭据。

证据：`server.dis.txt:6112`（UI token）、`:6175`（admin）、`:6232`（Origin）、`:6286`（Host）、`:6620`（跨站）、`:6698`（中间件）、`:23439`（UI cookie）。

### 参数、响应与错误约定

- 下文 Query 表完全来自函数注解与默认值。`必填` 与 `默认 null` 不同。`Request` 是框架注入，不是用户应传的参数。
- 所有正文入口都是 `payload: dict = Body(...)`：**JSON 对象 body 必填**，但没有为内部字段定义 Pydantic BaseModel。字段类型/默认值是 handler 的实际读取、转换与约定，不是额外 schema 强约束；未知字段通常不使用。
- Query/Body 的框架层缺失或类型错误通常是 HTTP 422。每条所列 error 是业务 handler 层；未捕获的底层异常可能 HTTP 500。大多数 `/dl/*` 业务失败仍返回 HTTP 200 + `ok:false`/`error`/`reason`，不要仅以 HTTP 200 判成功。
- 返回字段按实际条件分支列出，不承诺每次同时出现；透传底层对象明确标出未固定 schema，不臆造字段。
- 共同下载设置 body（`/dl/submit`、`/dl/library/update`）：`quality` 允许 1080p/720p/540p/480p/360p，默认或非法值回退 1080p；`series`（兼容 `series_at_once`）默认 2；`episodes`（兼容 `concurrency`）默认 4。两个并发量可转 int 且须在 1–16，bool/转换失败/越界回退各自默认；最后 episodes 不超过 `16 // series`。返回 settings 为 `{quality,series,episodes,workers,max_conn}`，workers=series×episodes、max_conn=16。证据 `server.dis.txt:10015`、`offline_dl.dis.txt:818`、`:2163`、`:43649`。
- **GET 不保证无副作用**：`/download` 提交下载、`/stream` 写媒体缓存、`/dl/diag` 写临时文件、`/dl/license/purchase-poll` 可激活许可，已逐项标注。

### 完整显式路由清单

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

### 逐项请求与响应

#### 1. GET `/`

实现：`index`，原 `server.py:726`；反汇编 [server.dis.txt:7292](evidence/server.dis.txt#L7292)。

鉴权/可见性：API key 豁免；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{service, ui, endpoints}`，旧 API 索引。

错误：无专门业务错误分支。

行为/副作用：只读。

#### 2. GET `/stats`

实现：`stats`，原 `server.py:737`；反汇编 [server.dis.txt:7320](evidence/server.dis.txt#L7320)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{uptime_s, requests, errors, risk, auth_fail, cache_backend, sign_backends, download_tasks}`；每个签名后端含 `{url, ready, pid}` 或 `{url, ready:false, error}`。

错误：管理 token 无效：HTTP 401 `需要 admin_token`。

行为/副作用：读取统计，向每个签名后端 `/` 发健康 GET。

#### 3. GET `/ui`

实现：`ui`，原 `server.py:757`；反汇编 [server.dis.txt:7539](evidence/server.dis.txt#L7539)。

鉴权/可见性：API key 豁免；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：HTML：`web/index.html`。

错误：文件缺失为框架/文件层错误。

行为/副作用：只读旧网页。

#### 4. GET `/img`

实现：`api_img`，原 `server.py:763`；反汇编 [server.dis.txt:7602](evidence/server.dis.txt#L7602)。

鉴权/可见性：不需 API key/UI token；仍受 Host/跨站和图片白名单限制。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `url` | query | str | 必填 | — |

返回：图片二进制；保留允许的 raster Content-Type，HEIC 可转 JPEG；带 Cache-Control、nosniff、CSP。

错误：HTTP 400 `图片域名不允许`；HTTP 404 `图片读取失败`（含重定向离开白名单、跳转过多、网络/格式错误）。

行为/副作用：访问白名单图片源并缓存；最多 4 轮跳转检查。

#### 5. GET `/admin`

实现：`admin_page`，原 `server.py:827`；反汇编 [server.dis.txt:8103](evidence/server.dis.txt#L8103)。

鉴权/可见性：页面本身不校验管理 token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：HTML：`web/admin.html`。

错误：页面本身没有 `_check_admin`；管理操作另行鉴权。

行为/副作用：只读管理网页。

#### 6. GET `/admin/keys`

实现：`admin_list_keys`，原 `server.py:833`；反汇编 [server.dis.txt:8166](evidence/server.dis.txt#L8166)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

声明参数：无（Request 若存在由框架注入）。

返回：`{keys, enabled_count}`；keys 为 KeyStore.list() 的透传列表，内部字段未在 handler 中固定。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：只读本地 API key 存储。

#### 7. POST `/admin/keys`

实现：`admin_gen_key`，原 `server.py:840`；反汇编 [server.dis.txt:8219](evidence/server.dis.txt#L8219)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `note` | query | str | `""` | — |

返回：`{ok:true, key, note}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**生成并持久化本地 API key**。`note` 是 query，不是 JSON body。

#### 8. POST `/admin/keys/revoke`

实现：`admin_revoke_key`，原 `server.py:848`；反汇编 [server.dis.txt:8276](evidence/server.dis.txt#L8276)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `key` | query | str | 必填 | — |
| `enable` | query | bool | `false` | — |

返回：`{ok: KeyStore.revoke(...) 的结果}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**修改指定 key 的 enabled 状态**；`enable=false` 撤销，`true` 恢复。参数为 query。

#### 9. DELETE `/admin/keys`

实现：`admin_delete_key`，原 `server.py:855`；反汇编 [server.dis.txt:8328](evidence/server.dis.txt#L8328)。

鉴权/可见性：ADMIN：x-admin-token 或 query admin_token；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `key` | query | str | 必填 | — |

返回：`{ok: KeyStore.delete(...) 的结果}`。

错误：HTTP 401 `admin_token 无效`。

行为/副作用：**删除本地 API key**。参数为 query。

#### 10. GET `/search`

实现：`api_search`，原 `server.py:862`；反汇编 [server.dis.txt:8377](evidence/server.dis.txt#L8377)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `q` | query | str | 必填 | — |
| `limit` | query | int | `null` | ge=1, le=40 |

返回：`{query, results}`，条目字段见 REQUEST_CHAIN。

错误：HTTP 500 `search失败: ...`。

行为/副作用：调用签名 APP 搜索/缓存。limit 未提供时由 H.search 的环境设置决定，通常 20。

#### 11. GET `/rank`

实现：`api_rank`，原 `server.py:871`；反汇编 [server.dis.txt:8451](evidence/server.dis.txt#L8451)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `board` | query | str | `"recommend"` | — |
| `limit` | query | int | `30` | — |

返回：`{board, name, items}`。

错误：未知 board：HTTP 400；上游异常：HTTP 500 `rank失败: ...`。

行为/副作用：读取平台榜单。合法 board 以 H.RANK_BOARDS 为准，索引示例 recommend/hot/new。

#### 12. GET `/latest`

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

#### 13. GET `/filters`

实现：`api_filters`，原 `server.py:900`；反汇编 [server.dis.txt:8701](evidence/server.dis.txt#L8701)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `genre` | query | str | `"short_play"` | — |

返回：`{genre, name, rows}`。

错误：未知 genre：HTTP 400；HTTP 500 `filters失败: ...`。

行为/副作用：读取平台分类筛选项。

#### 14. GET `/browse`

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

#### 15. GET `/episodes`

实现：`api_episodes`，原 `server.py:937`；反汇编 [server.dis.txt:9007](evidence/server.dis.txt#L9007)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | 必填 | — |

返回：`{meta, episodes}`，完整剧信息与每集模型，见 REQUEST_CHAIN。

错误：HTTP 500 `episodes失败: ...`。

行为/副作用：读取 APP 剧详情/缓存。

#### 16. POST `/metrics/batch`

实现：`api_metrics_batch`，原 `server.py:946`；反汇编 [server.dis.txt:9085](evidence/server.dis.txt#L9085)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list 或逗号分隔 str`；也兼容 `series_id`；必需得到非空 ID 集合，最多 200。`batch_size: 可转 int=20`，有效批大小限制 1–20。

返回：`{count, items, failed, batch_size}`。

错误：空 ID 或超过 200：HTTP 400；平台查询异常：HTTP 500 `metrics batch失败`。body 内类型不受 Pydantic 字段模型约束，转换失败可能成为 500。

行为/副作用：批量读取剧详情指标。

#### 17. GET `/play`

实现：`api_play`，原 `server.py:967`；反汇编 [server.dis.txt:9298](evidence/server.dis.txt#L9298)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | 必填 | — |
| `ep` | query | str | `"all"` | — |

返回：`{series_id, title, note, episodes}`；集条目 `{index, vid, title, duration, encrypted_url, backup, size, definition, stream_url}`。note 明示 encrypted_url 是 CENC 密文地址。

错误：HTTP 500 `play失败: ...`。

行为/副作用：查询详情与视频模型；ep 支持 all 或集数范围。返回可播放路径 `/stream?vid=...` 与远端密文 URL，不在本接口写媒体。

#### 18. GET `/download`

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

#### 19. GET `/download/status`

实现：`api_download_status`，原 `server.py:1000`；反汇编 [server.dis.txt:9602](evidence/server.dis.txt#L9602)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `task_id` | query | str | `null` | — |

返回：H.manager().status(task_id) 的透传结果；具体任务状态 schema 未在 handler 定义。

错误：未在 handler 显式捕获错误。

行为/副作用：只读任务状态。

#### 20. GET `/video_url`

实现：`api_video_url`，原 `server.py:1005`；反汇编 [server.dis.txt:9635](evidence/server.dis.txt#L9635)。

鉴权/可见性：API：x-api-key 或 query api_key，有效 key 并限流；安装版先被 404 隔离。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `vid` | query | str | 必填 | — |

返回：`{vid, url, backup, size, definition}`。

错误：没有 URL：HTTP 404 `无直链`；其它异常：HTTP 500 `video_url失败`。

行为/副作用：查询视频模型/缓存，URL 可能是加密媒体，不等于可直接播放文件。

#### 21. GET `/stream`

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

#### 22. POST `/dl/submit`

实现：`dl_submit`，原 `server.py:1204`；反汇编 [server.dis.txt:11345](evidence/server.dis.txt#L11345)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`text: str=""`；`series_ids: list=[]`；`ranges: object={}`；`scores: object={}`；下载设置见公共 body 说明。

返回：成功 `{ok:true, settings}`；部分许可受限另加 `blocked, need_license, free_limit, free_used`；全部受限 `{ok:false, reason, blocked, free_limit, free_used}`。

错误：业务 JSON `{ok:false,error}`：queue is empty、已有下载运行；许可失败由 reason/blocked 表示。

行为/副作用：**启动后台下载/写文件**，清理 live 状态、取消标记，执行许可检查。

#### 23. GET `/dl/search`

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

#### 24. GET `/dl/search/seasons`

实现：`dl_search_seasons`，原 `server.py:1318`；反汇编 [server.dis.txt:12321](evidence/server.dis.txt#L12321)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `q` | query | str | `""` | — |

返回：`{series, related, complete, extra}`，可附 query、backup；具体条带字段来自 `_search_strip`。

错误：异常在上述结构附 `error`，complete=false；空/过长 q 返回空结果。

行为/副作用：查询/补全搜索关联续季信息。

#### 25. GET `/dl/rank`

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

#### 26. POST `/dl/rank-episodes`

实现：`dl_rank_episodes`，原 `server.py:1351`；反汇编 [server.dis.txt:12596](evidence/server.dis.txt#L12596)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list=[]`；不是 list 则按空列表处理，最多传前 120 个。

返回：`{eps: ODL.hgdj_episodes(...) 的结果}`。

错误：异常 `{eps:{},error}`。

行为/副作用：读取网页集数信息。

#### 27. GET `/dl/preview`

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

#### 28. GET `/dl/explorer`

实现：`dl_explorer`，原 `server.py:1408`；反汇编 [server.dis.txt:13045](evidence/server.dis.txt#L13045)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `page` | query | int | `1` | — |
| `size` | query | int | `18` | — |

返回：`{results,page,pages,total,size}`。

错误：未显式捕获转换异常；内部目录不可用行为由 `_explorer_catalog` 决定。

行为/副作用：读取/缓存 explorer 目录，page 至少 1，size 1–60，默认 18。

#### 29. GET `/dl/episodes`

实现：`dl_episodes`，原 `server.py:1437`；反汇编 [server.dis.txt:13278](evidence/server.dis.txt#L13278)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `series_id` | query | str | `""` | — |

返回：`{series_id,title,cover,total,episodes}`，episodes 是排序去重的集序号，不是完整集对象。

错误：缺 ID `{episodes:[],error:"no series_id"}`；异常 `{episodes:[],error}`。

行为/副作用：查询剧详情/缓存。

#### 30. POST `/dl/resolve`

实现：`dl_resolve`，原 `server.py:1452`；反汇编 [server.dis.txt:13425](evidence/server.dis.txt#L13425)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`text: str=""`，分享链接或多行分享文本。

返回：`{resolved:[...]}`；成功条目 `{series_id,title,total,cover}`；busy 条目含 `error,busy`；不可用条目含 `hg_id,error,unavailable`；未识别含 `error:"unresolved"`。

错误：单个解析错误放在 resolved 条目；handler 自身未统一 catch。

行为/副作用：并发解析分享链接/榜单，最多 8 worker；可能访问远端网页。

#### 31. GET `/dl/status`

实现：`dl_status`，原 `server.py:1506`；反汇编 [server.dis.txt:13572](evidence/server.dis.txt#L13572)。

鉴权/可见性：UI token 可选；无 token 仅返回 running。

声明参数：无（Request 若存在由框架注入）。

返回：没有 UI token 仅 `{running:bool}`。有 token 返回 `{running,started,mode,series,log}` 加速率/字节/活动数/集计数/settings/source；library 模式还含 phase/checked/to_check/found/unread/seasons。

错误：本接口是 UI token 豁免项，未授权不会收到完整日志/路径。

行为/副作用：只读任务与实时进度，部分异常回退快照。

#### 32. GET `/dl/signhealth`

实现：`dl_signhealth`，原 `server.py:1588`；反汇编 [server.dis.txt:14172](evidence/server.dis.txt#L14172)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,fail}`，H.sign_stats()。

错误：无专门捕获分支。

行为/副作用：只读签名成功/失败计数。

#### 33. POST `/dl/signer-restarted`

实现：`dl_signer_restarted`，原 `server.py:1598`；反汇编 [server.dis.txt:14212](evidence/server.dis.txt#L14212)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：无专门捕获分支。

行为/副作用：**改变签名器冷启动状态并启动后台预热**。此接口是“通知已重启”，不是直接杀进程。

#### 34. GET `/dl/diag`

实现：`dl_diag`，原 `server.py:1608`；反汇编 [server.dis.txt:14251](evidence/server.dis.txt#L14251)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{pid,web_port,bind_host,sign_server,signer_healthy,output_dir,output_writable,output_write_error,state_dir,data_dir,python,tls_trust,running,mode,app_log,dl_log}`。

错误：可写测试错误写入 output_write_error；签名测试异常写为不健康。

行为/副作用：**GET 也会创建输出目录、写入并删除 .hg_write_test、调用签名探测**；读取日志。

#### 35. GET `/dl/config`

实现：`dl_config_get`，原 `server.py:1727`；反汇编 [server.dis.txt:15273](evidence/server.dis.txt#L15273)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{output_dir}`。

错误：无专门捕获分支。

行为/副作用：只读下载输出目录。

#### 36. POST `/dl/config`

实现：`dl_config_set`，原 `server.py:1732`；反汇编 [server.dis.txt:15298](evidence/server.dis.txt#L15298)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`output_dir: str=""`。

返回：成功 `{ok:true,output_dir}`。

错误：失败 `{ok:false,error,output_dir}`。

行为/副作用：**修改下载输出目录并持久化 dlconfig.json**。

#### 37. POST `/dl/open`

实现：`dl_open`，原 `server.py:2204`；反汇编 [server.dis.txt:18487](evidence/server.dis.txt#L18487)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,output_dir}`。

错误：`{ok:false,error,output_dir}`。

行为/副作用：**创建输出目录并打开系统文件管理器**。

#### 38. POST `/dl/bugreport`

实现：`dl_bugreport`，原 `server.py:2245`；反汇编 [server.dis.txt:18849](evidence/server.dis.txt#L18849)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`logs: bool=true`，`screenshot: bool=false`，均经 bool()。

返回：`{ok:true,path,included}`，本地 bugreport ZIP。

错误：`{ok:false,error}`；截图失败可写入 ZIP 内 screenshot-FAILED.txt。

行为/副作用：**写日志 ZIP，可截图并打开文件管理器定位文件**；该 handler 没有自动上传报告。

#### 39. POST `/dl/pick`

实现：`dl_pick`，原 `server.py:2576`；反汇编 [server.dis.txt:20727](evidence/server.dis.txt#L20727)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：Windows 原生目录选择器结果（通常 `{ok,path}`，其它错误键来自 `_pick_folder`）。

错误：非 Windows `{ok:false,error:"folder picker is Windows-only here — type the path instead"}`。

行为/副作用：**打开系统选目录对话框/子进程**；不自动提交配置。

#### 40. GET `/dl/library`

实现：`dl_library`，原 `server.py:2586`；反汇编 [server.dis.txt:20789](evidence/server.dis.txt#L20789)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{items,root}`；item 含 `{name,series_id,title,local,total,new,fresh,score,updated,size,poster,cover,h264}`。底层证据 `offline_dl.dis.txt:18670`。

错误：扫描异常 `{items:[],error}`。

行为/副作用：**扫描本地下载库，seen_at 尚无有效值时可写入已看时间基线**；不发起媒体下载。

#### 41. GET `/dl/library/episodes`

实现：`dl_library_episodes`，原 `server.py:2594`；反汇编 [server.dis.txt:20857](evidence/server.dis.txt#L20857)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |

返回：`{name,title,total,downloaded,fresh,episodes,h264}`；episodes 条目为 `{index,fresh}`。底层证据 `offline_dl.dis.txt:19081`（源行 2119、2132）。

错误：不安全/空目录名，或目录不存在：HTTP 404 `series not found`。

行为/副作用：只读本地剧目录。

#### 42. POST `/dl/library/seen`

实现：`dl_library_seen`，原 `server.py:2606`；反汇编 [server.dis.txt:20924](evidence/server.dis.txt#L20924)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list` 可批量；否则 `name: str=""`。

返回：批量 `{ok:true,count}`；单项 `{ok:bool}`。

错误：无效名不标记；未设置统一异常捕获。

行为/副作用：**持久化已看/已知状态**。

#### 43. POST `/dl/library/delete`

实现：`dl_library_delete`，原 `server.py:2623`；反汇编 [server.dis.txt:21048](evidence/server.dis.txt#L21048)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list=[]`，逐个名称清理/校验。

返回：ODL.library_delete 结果，含 `{ok,moved,errors}`；moved 条目含恢复 token。

错误：异常 `{ok:false,moved:[],errors:{"*":错误}}`；如果移动结果不属于用户请求，自动恢复并记 `not the series asked for (left in place)`。

行为/副作用：**将所选库目录移入可恢复位置**；接口名 delete 不等于立即永久擦除。

#### 44. POST `/dl/library/restore`

实现：`dl_library_restore`，原 `server.py:2649`；反汇编 [server.dis.txt:21296](evidence/server.dis.txt#L21296)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`token: str=""`，由 delete 返回。

返回：`{ok:true,name}`，透传 ODL.library_restore。底层证据 `offline_dl.dis.txt:19873`。

错误：`{ok:false,error}`：not in trash、已有同名剧目录、文件操作失败。

行为/副作用：**将 .trash 下之前移走的库目录恢复到输出根目录**。

#### 45. POST `/dl/library/merge`

实现：`dl_library_merge`，原 `server.py:2663`；反汇编 [server.dis.txt:21380](evidence/server.dis.txt#L21380)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`variant: str="original"`，只允许 original/h264，否则回退 original。

返回：`{ok:true,started:true}`；进度另查 merge-status。

错误：无名称 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`。

行为/副作用：**后台合并剧集并写合并媒体**，状态含 variant。

#### 46. GET `/dl/library/merge-status`

实现：`dl_library_merge_status`，原 `server.py:2693`；反汇编 [server.dis.txt:21577](evidence/server.dis.txt#L21577)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{running,name,pct,file,error,done,variant}`，合并状态副本。

错误：无专门错误分支。

行为/副作用：只读。

#### 47. POST `/dl/library/convert`

实现：`dl_library_convert`，原 `server.py:2706`；反汇编 [server.dis.txt:21603](evidence/server.dis.txt#L21603)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list` 或 `name`；`keep_original: bool=true`；`mode: str="auto"`（auto/gpu/cpu）；`speed: str="quality"`（quality/balanced/fast）；`threads: 可转int=0`，限制 0–64。

返回：`{ok:true,started:true}`；进度另查 convert-status。

错误：无剧名 `{ok:false,error:"no series"}`；已有任务 `{ok:false,busy:true,error}`；无效 mode/speed 回退默认。

行为/副作用：**后台转码写 H264 文件**；keep_original 传入转换流程，涉及原文件保留策略。

#### 48. POST `/dl/library/convert-cancel`

实现：`dl_library_convert_cancel`，原 `server.py:2759`；反汇编 [server.dis.txt:21942](evidence/server.dis.txt#L21942)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：异常 `{ok:false,error}`。

行为/副作用：**请求取消转码**。

#### 49. GET `/dl/library/convert-status`

实现：`dl_library_convert_status`，原 `server.py:2769`；反汇编 [server.dis.txt:22020](evidence/server.dis.txt#L22020)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{running,name,pct,encoder,mode,speed,total,series_done,converted,skipped,failed,error,done}`。

错误：无专门错误分支。

行为/副作用：只读转码状态。

#### 50. GET `/dl/poster`

实现：`dl_poster`，原 `server.py:2775`；反汇编 [server.dis.txt:22046](evidence/server.dis.txt#L22046)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |

返回：`image/jpeg` FileResponse，读取所选目录 poster.jpg，Cache-Control max-age=3600。

错误：HTTP 404 `no poster`。

行为/副作用：只读本地海报。

#### 51. POST `/dl/library/open`

实现：`dl_library_open`，原 `server.py:2785`；反汇编 [server.dis.txt:22132](evidence/server.dis.txt#L22132)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`sub: str=""`（如 H264），经 `_safe_series_name` 校验。

返回：`{ok:true}`。

错误：`{ok:false,error}`：folder not found/no converted files yet/系统异常。

行为/副作用：**打开所选剧目录或子目录**。

#### 52. POST `/dl/library/play`

实现：`dl_library_play`，原 `server.py:2803`；反汇编 [server.dis.txt:22309](evidence/server.dis.txt#L22309)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`name: str=""`；`ep: 可转int/未提供=null`，内部从本地 MP4 文件名解析序号；省略、无法转 int 或未找到集号时，回退到按序号排序的第一个本地 MP4。

返回：`{ok:true,file}`。

错误：`{ok:false,error}`：folder not found/no episodes downloaded yet/系统异常。

行为/副作用：**在系统默认播放器打开本地集文件**；Windows startfile，macOS open，其它 xdg-open。

#### 53. GET `/dl/library/file`

实现：`dl_library_file`，原 `server.py:2842`；反汇编 [server.dis.txt:22670](evidence/server.dis.txt#L22670)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `name` | query | str | `""` | — |
| `ep` | query | int | `0` | — |

返回：`video/mp4` FileResponse，Cache-Control no-store；优先找 第NNN集.mp4，随后按 MP4 文件名内数字匹配。

错误：HTTP 404 `series not found` / `episode not found`。

行为/副作用：只读取所选库内媒体，安全名称校验。

#### 54. POST `/dl/library/update`

实现：`dl_library_update`，原 `server.py:2879`；反汇编 [server.dis.txt:23075](evidence/server.dis.txt#L23075)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`names: list/未提供`；下载设置见公共 body；未提供名称时可交底层进行库更新，明确给出的名称需合法。

返回：`{ok:true,settings}`。

错误：`{ok:false,error}`：invalid series name(s)、已有 download/update 运行。

行为/副作用：**后台检查库更新并下载缺集，写文件**，与主下载队列互斥。

#### 55. POST `/dl/library/seasons/decline`

实现：`dl_library_seasons_decline`，原 `server.py:2901`；反汇编 [server.dis.txt:23278](evidence/server.dis.txt#L23278)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`series_ids: list=[]`，最多检查前 200 个，ID 必须匹配 15–20 位十进制。

返回：`{ok:true,declined}`。

错误：`{ok:false,error:"no series ids"}`。

行为/副作用：**记录拒绝的续季提示状态**。

#### 56. POST `/dl/cancel`

实现：`dl_cancel`，原 `server.py:2918`；反汇编 [server.dis.txt:23398](evidence/server.dis.txt#L23398)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true}`。

错误：无专门错误分支。

行为/副作用：**设置取消下载标志**；日志说明完成已在途集，不再启动新集。

#### 57. GET `/dl`

实现：`dl_page`，原 `server.py:2925`；反汇编 [server.dis.txt:23439](evidence/server.dis.txt#L23439)。

鉴权/可见性：UI bootstrap；不要求已有 UI token。

声明参数：无（Request 若存在由框架注入）。

另从 request.query_params 读取 `k: str=""`，它不在函数签名中。

返回：若 query `k` 与 HG_UI_TOKEN 匹配：303 跳转 `/dl` 并设置 token cookie；否则返回 web/downloader.html，Cache-Control no-store。

错误：token 不匹配不会建立会话；页面可显示，受保护 API 仍拒绝。

行为/副作用：成功 bootstrap 时**设置 HttpOnly、SameSite=strict、path=/dl 的 UI cookie**。

#### 58. GET `/dl/license/status`

实现：`dl_license_status`，原 `server.py:2945`；反汇编 [server.dis.txt:23561](evidence/server.dis.txt#L23561)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.status() 透传对象；handler 未声明固定 schema（许可模块接口参见远端 API 文档）。

错误：未统一捕获 LIC.status 异常。

行为/副作用：读取许可状态，底层可能刷新缓存。

#### 59. POST `/dl/license/activate`

实现：`dl_license_activate`，原 `server.py:2950`；反汇编 [server.dis.txt:23585](evidence/server.dis.txt#L23585)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`key: str=""`。

返回：LIC.activate(key) 透传许可结果；字段由许可模块决定。

错误：失败 reason/错误由 LIC.activate 决定；handler 无统一 catch。

行为/副作用：**尝试激活许可并更新本机许可状态**。

#### 60. POST `/dl/license/deactivate`

实现：`dl_license_deactivate`，原 `server.py:2955`；反汇编 [server.dis.txt:23624](evidence/server.dis.txt#L23624)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.deactivate() 透传结果。

错误：错误由许可模块决定。

行为/副作用：**解绑/停用本机许可**。

#### 61. POST `/dl/license/reactivate`

实现：`dl_license_reactivate`，原 `server.py:2960`；反汇编 [server.dis.txt:23648](evidence/server.dis.txt#L23648)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：有 current_key 时透传 LIC.activate(current_key)。

错误：无 key：`{ok:false,reason:"no_key"}`。

行为/副作用：**使用已保存 key 重新激活**。

#### 62. GET `/dl/license/usage`

实现：`dl_license_usage`，原 `server.py:2970`；反汇编 [server.dis.txt:23698](evidence/server.dis.txt#L23698)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：LIC.usage() 透传统计；handler 未固定字段。

错误：错误由许可模块决定。

行为/副作用：读取许可用量。

#### 63. GET `/dl/license/plans`

实现：`dl_license_plans`，原 `server.py:3022`；反汇编 [server.dis.txt:24002](evidence/server.dis.txt#L24002)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：支付服务 GET /plans 的 JSON 透传，缓存 600 秒。

错误：`{plans:[],error:"unavailable"}`。

行为/副作用：网络读取方案/更新缓存。

#### 64. POST `/dl/license/buy`

实现：`dl_license_buy`，原 `server.py:3040`；反汇编 [server.dis.txt:24137](evidence/server.dis.txt#L24137)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`plan: str=""`，只允许 month/year/life。

返回：`{ok:true,session_id,url}`。

错误：`{ok:false,reason}`：bad_plan/no_session/bad_checkout_url；网络失败另有 detail（截断 200 字）。

行为/副作用：**创建结账会话并打开浏览器支付页**；不是已完成付款。

#### 65. GET `/dl/license/purchase-poll`

实现：`dl_license_purchase_poll`，原 `server.py:3067`；反汇编 [server.dis.txt:24374](evidence/server.dis.txt#L24374)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `session_id` | query | str | `""` | — |

返回：pending 分支 `{pending:true,reason}`；拿到 key 后返回 `{pending:false,ok,activated,reason,usage}`。

错误：缺 session `{pending:false,ok:false,reason:"no_session"}`；网络 pending=true,reason=network；未就绪 reason=not_ready 或服务端 reason。

行为/副作用：**GET 若取回 key 会自动调用 LIC.activate**，并非严格只读。

#### 66. POST `/dl/license/manage`

实现：`dl_license_manage`，原 `server.py:3088`；反汇编 [server.dis.txt:24562](evidence/server.dis.txt#L24562)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,url}`。

错误：`{ok:false,reason}`：no_key/unavailable/bad_portal_url；网络失败附 detail。

行为/副作用：**用当前 key/device 创建管理门户并打开浏览器**。

#### 67. GET `/dl/update-check`

实现：`dl_update_check`，原 `server.py:3121`；反汇编 [server.dis.txt:24822](evidence/server.dis.txt#L24822)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,current,latest,update,url,page,name,notes}`；失败/无可用结果 `{ok:false,current,update:false}`。

错误：网络等异常转上述失败结构；说明 notes 最多 800 字。

行为/副作用：GET GitHub latest release，缓存 1800 秒；不下载安装包。

#### 68. POST `/dl/update-download`

实现：`dl_update_download`，原 `server.py:3161`；反汇编 [server.dis.txt:25200](evidence/server.dis.txt#L25200)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok,path,name,sha256,signed,valid,publisher,expected_publisher,trusted}`。

错误：busy `{ok:false,busy:true,error}`；无可信下载 URL/下载失败 `{ok:false,error}`。

行为/副作用：**下载 exe 到本地 update 目录、计算 SHA-256、调用 PowerShell Authenticode 检验**；仅允许预期 GitHub release 路径，不在此 handler 执行。

#### 69. GET `/dl/update-progress`

实现：`dl_update_progress`，原 `server.py:3239`；反汇编 [server.dis.txt:25972](evidence/server.dis.txt#L25972)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

声明参数：无（Request 若存在由框架注入）。

返回：`{ok:true,state,pct,downloaded,total,error}`。state 可 idle/starting/downloading/verifying/done/error。

错误：无专门错误分支。

行为/副作用：只读更新下载进度。

#### 70. POST `/dl/update-run`

实现：`dl_update_run`，原 `server.py:3245`；反汇编 [server.dis.txt:26004](evidence/server.dis.txt#L26004)。

鉴权/可见性：UI：设置 HG_UI_TOKEN 时需 cookie 或 x-hg-token；公共 Host/跨站校验。

| 参数 | 位置 | 声明类型 | 必填/默认值 | 约束 |
|---|---|---|---|---|
| `payload` | body | dict | 必填 | — |

Body 字段：`path: str=""`，必须是本进程已下载记录对应 exe。

返回：`{ok:true}`。

错误：`{ok:false,error}`：unknown download、非 exe、无校验记录、SHA-256 改变、无法验签、预期发布者校验未通过。

行为/副作用：**经路径/记录/hash/发布者检查后使用 os.startfile 执行安装程序**。

### 框架自动路由与没有注册的路径

`server.py` 以 `FastAPI(title="红果短剧 API", version="1.0")` 初始化，未传 docs_url、redoc_url、openapi_url 开关（`server.dis.txt:956`）。已从安装器提取并校验 **FastAPI 0.141.1** 源码：其 [applications.py:1105](extracted/python/Lib/site-packages/fastapi/applications.py#L1105) setup 确定增加下列 4 条框架路径；[Starlette routing.py:224](extracted/python/Lib/site-packages/starlette/routing.py#L224) 的 Route 默认 GET 且追加 HEAD。因此是 **70 条显式 method/path + 8 条框架 method/path = 78 条组合**，框架路由机器表见 [framework-routes.json](evidence/framework-routes.json)。

| 方法 | 路径 | 请求参数 | 返回 | 非安装模式鉴权 | 副作用 |
|---|---|---|---|---|---|
| GET / HEAD | `/openapi.json` | 无业务参数，Request 注入 | OpenAPI JSON（HEAD 无 body） | API key 豁免 | 生成/缓存 schema |
| GET / HEAD | `/docs` | 无业务参数，Request 注入 | Swagger UI HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |
| GET / HEAD | `/docs/oauth2-redirect` | 框架 OAuth redirect 页面，参数由其 JS 使用，业务 server 未声明 | OAuth redirect HTML（HEAD 无 body） | **不在豁免清单，需 API key** | 浏览器 OAuth 回跳处理 |
| GET / HEAD | `/redoc` | 无业务参数，Request 注入 | ReDoc HTML（HEAD 无 body） | API key 豁免 | 无业务修改 |

安装模式中，上述四条路径均先被过滤返回 404；非安装模式中的中间件错误（Host、401、429）仍按本文公共规则。HEAD 的自动补充仅在上述 Starlette Route 确认，不额外将 70 条 app.get 业务路由都臆计为支持 HEAD。

`/favicon.ico` 在中间件放行及 API key 豁免清单，但 **没有找到显式 handler 注册**；不要将其当作已实现的图片接口。没有发现本业务模块的动态 add_api_route/include_router/mount 追加路由。

### 与前端请求交叉核对及可复现性

提取的 `app/web/downloader.html`、`index.html`、`admin.html` 中页面请求用于交叉验证：桌面页使用 `/dl/*` 与 `/img`；旧页面使用 `/search`、`/rank`、`/latest`、`/filters`、`/browse`、`/episodes`、`/play`、`/download` 等；管理页面使用 `/admin/keys`、`/admin/keys/revoke`。证据 [index.html:59](extracted/app/web/index.html#L59)、[admin.html:47](extracted/app/web/admin.html#L47)、[downloader.inline.js:372](evidence/downloader.inline.js#L372)。外部 explorer 域名请求不应误计为本地注册路由。

该清单按程序声明完整覆盖 70 条 method+path 组合，`GET /admin/keys`、`POST /admin/keys`、`DELETE /admin/keys` 与 `GET/POST /dl/config` 分别计数。当前没有运行原 server，也没有通过调用写接口来猜返回值；需验证的动态环境行为与透传模块扩展字段均保留为明确边界。


<a id="signer-api"></a>

## 二、本地签名服务

此服务由安装包的 `app/sign/unidbg-sign.jar` 中 `com.hongguo.sign.FqTrace` 提供，供 Python 后端在调用平台 API 前生成请求头。这里的 `X-Sign-Token` 是本地进程的访问令牌，与平台签名头、用户许可证、旧版 API key 是不同凭据。

### 服务地址与生命周期

| 场景 | 地址 |
|---|---|
| 原启动器正常启动 | 默认 `http://127.0.0.1:9099`，受 `HG_SIGN_PORT` 和端口选择逻辑影响 |
| 直接运行 Jar 的 `serve`，省略端口 | 默认 `http://127.0.0.1:9090` |
| 本次实现的导出脚本 | `127.0.0.1` 的空闲临时端口，退出时关闭 |
| 服务绑定地址 | Jar 读取 `BIND_HOST`，默认 `127.0.0.1` |

原进程启动方式（工作目录是 `app/sign`）：

```bash
java -Xmx1024m -XX:+ExitOnOutOfMemoryError \
  --add-opens java.base/java.lang=ALL-UNNAMED \
  -cp unidbg-sign.jar com.hongguo.sign.FqTrace serve 9099
```

`HG_SIGN_TOKEN` 非空时启用鉴权。原启动器以及本次脚本在每次启动生成随机令牌，再传给服务与调用方；令牌不会作为平台请求头发往 fqnovel。Java 类文件 major version 61，即需要 Java 17 或更高版本。

证据：`launcher.dis.txt:958` / `app.dis.txt:8295`；`FqTrace.javap.txt:837`（serveStatic）、`:949`（main）。本次在 Mac ARM64 上实际启动成功。

### POST /sign

这是 `FqTrace` 明确注册的唯一 HTTP context。调用方使用 POST；Java handler 本身未检查 HTTP method，协议仍应按 POST JSON 使用。

请求头：

| Header | 要求 | 说明 |
|---|---|---|
| `Content-Type` | 调用方发送 | `application/json` |
| `X-Sign-Token` | 服务启用鉴权时必需 | 必须与该服务进程的 `HG_SIGN_TOKEN` 相等 |

请求 JSON：

| 字段 | 类型 | 含义 |
|---|---|---|
| `url` | string | 平台请求完整 URL，包含 URL 编码后的 query 和 `_rticket` |
| `headers` | object<string,string> | 准备发送给平台的请求头；POST 的 `x-ss-stub` 必须已经计算好 |

```json
{
  "url": "https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/search/tab/v?<完整查询参数>",
  "headers": {
    "user-agent": "<配置中的 user-agent>",
    "content-type": "application/json; charset=utf-8",
    "passport-sdk-version": "5051452",
    "sdk-version": "2",
    "x-tt-store-region": "kh",
    "x-tt-store-region-src": "uid"
  }
}
```

响应 HTTP 200 为签名头字典。本次实测包含：

```json
{
  "X-Argus": "<每请求生成>",
  "X-Gorgon": "<每请求生成>",
  "X-Helios": "<每请求生成>",
  "X-Khronos": "<每请求生成>",
  "X-Ladon": "<每请求生成>",
  "X-Medusa": "<每请求生成>",
  "X-Neptune": "<每请求生成>",
  "X-Soter": "<每请求生成>"
}
```

调用方把响应合并进原 headers，再发送同一 URL 与同一 body 字节。签名服务不替调用方发送平台请求，不能把 `POST /sign` 成功当成平台业务请求成功。

错误形态：

- 缺失或错误令牌：HTTP 401，`{"error":"unauthorized"}`。
- handler 异常：HTTP 200，包含 `error` 字段；必须检查 JSON，不能只检查 HTTP 状态码。
- `sign()` 返回 null 时，`signMap()` 可返回 `{}`。本次用不完整查询参数试签时实际遇到过空字典；脚本将它视为失败。
- 首次请求可能等待模拟器初始化。工作线程持有模拟器，HTTP handler 排队等待结果，因此不能据 HTTP 端口已监听推断初始化全部完成。

证据：`FqTrace.javap.txt:1048`（handler）、`:786` 附近（signMap）、`:1201`（工作线程）。

### 请求体哈希

平台 POST body 使用紧凑 JSON 的 UTF-8 字节：

```python
body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
headers["x-ss-stub"] = hashlib.md5(body_bytes).hexdigest().upper()
```

`/sign` 只收到 URL 和 headers，不单独收到平台 JSON body；它使用已计算的 body 哈希。签名后再改变 body 序列化方式会破坏一致性。

### 其他签名部署的兼容调用

Python 代码还包含向可配置 `SIGN_SERVER` 发 `GET /grab`（刷新 query/session headers）和 `GET /`（读取健康/ready/pid）的调用。这两个路径**未被随包 `FqTrace` HTTP 服务注册**，属于其他签名服务部署的兼容接口，详细调用约定见外部 API 部分。本次导出脚本仅依赖 `/sign`。


<a id="remote-api"></a>

## 三、外部服务接口

本文件记录这份安装器的**调用端实际使用到的出站 HTTP 路径**，包括业务 API、公开网站 SSR、分享解析和动态资源模板。不是服务端完整 OpenAPI；响应字段是客户端消费到的字段，未被读取的远端字段仍可能存在。

静态核查覆盖 10 个业务 Python 字节码文件和打包下载器前端，共整理 **33 个出站路径/模板**。同路径的调用变体合并；没有新增调用许可、支付、更新、遥测或其他远端接口。机器清单：[remote-routes.json](evidence/remote-routes.json)。

已有搜索→详情→模型实测证据可以作为核心三接口的补充；其余项目以本文件的静态 evidence 为界，不声称已实测可用。所有许可证、anon key、设备 secret、session_id/token 的真实值均省略。

### 1. 红果 App API 公共协议

默认 `https://api5-normal-sinfonlinec.fqnovel.com`，来自 `config.json.api_host`。原程序还定义备用 `https://api5-normal-sinfonlineb.fqnovel.com`，在 `api()` 的异常恢复路径使用。备用是同一路径重新签名请求，不是不同的业务接口。

URL 参数按 `config.base_query → devicepool.current().query → 业务 extra_query → _rticket` 顺序覆盖，`_rticket=str(int(time.time()*1000))`；键顺序保留，值通过 `quote(str(v), safe="")` 编码（空格是 `%20`）。没有看到另加一个名为 `timestamp` 的查询字段。

通用查询字段（设备ID已替换为占位符）：

```json
{
  "aid": "8662",
  "compliance_status": "0",
  "is_android_pad_screen": "0",
  "device_brand": "Samsung",
  "cdid": "<device identifier>",
  "iid": "<device identifier>",
  "rom_version": "V417IR release-keys",
  "version_code": "72932",
  "dpi": "480",
  "device_id": "<device identifier>",
  "host_abi": "arm64-v8a",
  "channel": "googleplay",
  "resolution": "1080*1920",
  "os_version": "15",
  "version_name": "7.2.9.32",
  "update_version_code": "72932",
  "language": "en",
  "player_so_load": "1",
  "manifest_version_code": "72932",
  "pv_player": "72932",
  "os": "android",
  "os_api": "35",
  "dragon_device_type": "phone",
  "need_personal_recommend": "1",
  "ac": "wifi",
  "app_name": "novelread",
  "device_type": "SM-S938U",
  "ssmix": "a",
  "device_platform": "android"
}
```

`session_headers` 包含 user-agent、passport-sdk-version、sdk-version、x-tt-store-region、x-tt-store-region-src 等。设备池启用时使用当前设备 UA，并移除 cookie/x-tt-token。所有业务请求设 `content-type: application/json; charset=utf-8`。POST body 使用 `json.dumps(..., ensure_ascii=False, separators=(",", ":")).encode("utf-8")`；`x-ss-stub` 为这些精确字节的 MD5 大写十六进制。

需要签名时，把完整 URL/headers 交给签名器，再合并返回 headers，删除 accept-encoding 后发请求。搜索/建议/计划/详情/模型/收藏调用默认 `signed=True`；榜单/分类调用显式 `signed=SIGN_LIST`，`HG_SIGN_LIST` 未设置时为 false。不可把它们全部写成默认强制签名。

主传输在 curl_cffi 可用时使用 `impersonate="chrome"`，也有 requests 回退。证书校验保持启用；`IMPERSONATE`、`HONGGUO_PROXY` 可配置。

公共实现证据：[build_url（原源码行482）](evidence/hongguo.dis.txt)，证据文件第 5449 行；[_req_headers（原源码行494）](evidence/hongguo.dis.txt)，证据文件第 5570 行；[_api_once（原源码行510）](evidence/hongguo.dis.txt)，证据文件第 5684 行；[api（原源码行543）](evidence/hongguo.dis.txt)，证据文件第 5954 行；[http_request（原源码行73）](evidence/hongguo.dis.txt)，证据文件第 2861 行。

`IMAGE_SHRINK` 是带换行的 base64 字符串，解码内容为 `[ {"image_type":3,"image_width":900,"shrink_type":3}, {"image_type":4,"image_width":54,"shrink_type":4} ]`。实现需要保留原请求中的精确字符串，不能只把解码后的数组直接放到字段里。

### 2. 分服务接口明细

#### 红果 App API

##### `official.search` — 搜索与搜索翻页

`GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/search/tab/v`

**Query**：

```json
{
  "query": "关键词 string",
  "tab_name": "feed",
  "search_source": "1",
  "offset": "0 或上页 next_offset",
  "count": "0",
  "use_correct": "true",
  "passback": "上页非空 passback 时带入",
  "search_id": "上页非空 search_id 时带入"
}
```

**Body**：无。

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。

**响应**：code/message；search_tabs[0].data[] 搜索卡片，book_id/search_result_id；video_data 可为 list 或 object，内有 video_detail；next_offset/passback/search_id/has_more 控制翻页。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 search() 原版最多12页/40条，分页 _search_page 另外支持 cursor。并非所有卡片都是剧集。

**静态证据**：[search（原源码行991）](evidence/hongguo.dis.txt)，证据文件第 9139 行；[_search_page（原源码行1515）](evidence/hongguo.dis.txt)，证据文件第 13452 行。

##### `official.suggest` — 搜索建议与系列匹配

`GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/search/suggest/v`

**Query**：

```json
{
  "q": "关键词 string（suggest() 限制长度≤60）",
  "count": "20",
  "search_source": "1",
  "tab_type": "11"
}
```

**Body**：无。

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。

**响应**：data.query_result_v2[]；消费 word_type_str、keyword、video_data.series_id/name/title/episode_cnt/score。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 同时用于服务恢复探测，不是另一条接口。

**静态证据**：[suggest（原源码行1355）](evidence/hongguo.dis.txt)，证据文件第 12380 行。

##### `official.plan` — 同 IP 系列/季/版本计划

`GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/plan/v`

**Query**：

```json
{
  "scene": "10",
  "from": "same_ip_same_series_land_page",
  "stick_ids": "series_id string",
  "offset": "0",
  "session_id": ""
}
```

**Body**：无。

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。

**响应**：data[] block → cell_data[] → video_data[]；消费 series_id/title/episode_cnt/score，组装同系列条目。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。

**静态证据**：[series_plan（原源码行1323）](evidence/hongguo.dis.txt)，证据文件第 12025 行。

##### `official.detail` — 整剧详情与分集目录

`POST https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_detail/v1/`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "biz_param": {
    "detail_page_version": 0,
    "disable_digg_stat": false,
    "disable_video_relate_book": false,
    "image_shrink_datas_str": "<IMAGE_SHRINK：下方公共协议给出解码后的 JSON>",
    "need_all_video_definition": false,
    "need_mp4_align": false,
    "screen_width_px": "900",
    "source": 7,
    "use_os_player": false,
    "use_server_dns": false
  },
  "series_id": "单个 series_id，批量时以英文逗号 join 多个 ID"
}
```

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。

**响应**：data[series_id].video_data：series_title/series_intro/episode_cnt/series_status/series_play_cnt/followed_cnt/create_time/series_cover/score/douban_score/rating/category_schema/celebrities/related_album_id/secondary_infos/related_novel_book_id；video_list[] 内有 vid_index/vid/title/duration/episode_cover/cover/comment_count/digged_count。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 data 的 key 是每部剧 ID；不是以 ID 列表另开 endpoint。响应缺集必须单独处理。

**静态证据**：[_episodes_body（原源码行1053）](evidence/hongguo.dis.txt)，证据文件第 9620 行；[get_episodes（原源码行1169）](evidence/hongguo.dis.txt)，证据文件第 10641 行；[get_episodes_batch（原源码行1217）](evidence/hongguo.dis.txt)，证据文件第 11113 行；[get_episodes_multi（原源码行1257）](evidence/hongguo.dis.txt)，证据文件第 11519 行；[_signed_lists（原源码行1278）](evidence/offline_dl.dis.txt)，证据文件第 11380 行。

##### `official.models` — 每集全部播放/下载码率模型

`POST https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_model/v1/`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "biz_param": {
    "detail_page_version": 0,
    "device_level": 3,
    "disable_digg_stat": false,
    "disable_video_relate_book": false,
    "need_all_video_definition": true,
    "need_mp4_align": false,
    "use_os_player": false,
    "use_server_dns": false,
    "video_platform": 1024
  },
  "mixed_video_id_map": {
    "1": [
      "<vid1>",
      "<vid2>"
    ]
  }
}
```

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。

**响应**：data[vid].video_model 是 JSON 字符串；json.loads 后 video_list[] 含 main_url、backup_url、video_meta（definition/size/bitrate/width/height/codec 等服务器字段）。原模型还可能包含加密标记、过期参数等；客户端不能将所有资源假设为未加密 MP4。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 批量 helpers 最多每批5个 ID；get_video_urls 只挑最大 size，get_video_tracks 保留全部 tracks。

**静态证据**：[get_video_urls（原源码行1964）](evidence/hongguo.dis.txt)，证据文件第 17484 行；[get_video_tracks（原源码行2003）](evidence/hongguo.dis.txt)，证据文件第 17799 行；[_video_model（原源码行1516）](evidence/offline_dl.dis.txt)，证据文件第 13543 行。

##### `official.collection` — 当前身份的收藏/追剧列表

`GET https://api5-normal-sinfonlinec.fqnovel.com/reading/user/subscribe/list/v0`

**Query**：

```json
{
  "subscribe_order_type": "0",
  "swipe_type": "0",
  "subscribe_offset": "offset string",
  "offset": "初始0，随后 next_offset",
  "tab_type": "默认逐个请求2/5/8",
  "limit": "page_limit，默认50",
  "is_online": "false",
  "need_calendar_schema": "false"
}
```

**Body**：无。

**认证/头**：official_signed：通用设备 query/session_headers + 签名器返回 headers；非 POST 不添加 body MD5。 有效会话可影响返回内容；设备池模式会去除原 cookie/x-tt-token。

**响应**：data.subscribe_items[]：detail_schema 中解析 series_id，回退 item_id；name/item_type；data.has_more/next_offset。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 这是读收藏，不是收藏/取消收藏写接口。

**静态证据**：[get_collection（原源码行1184）](evidence/hongguo.dis.txt)，证据文件第 10796 行。

##### `official.rank` — 榜单、漫剧榜单与分页

`GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/bookmall/cell/change/v`

**Query**：

```json
{
  "cell_id": "7470092475068071998",
  "tab_type": "26",
  "client_req_type": "2",
  "client_template": "2",
  "screen_width_px": "1350",
  "session_uuid": "uuid4 string",
  "selected_items": "all | human | comic_series_rank | ai_playlet",
  "sub_selected_items": "榜单映射，见下方",
  "offset": "非0时添加分页 offset"
}
```

**Body**：无。

**认证/头**：official_optional_signature：通用 query/session_headers；signed=SIGN_LIST，HG_SIGN_LIST 缺省为 false，可由环境设为 true。

**响应**：data.cell_view.cell_data[]，每个 cell.video_data；series_id 或 book_id，title/episode_cnt/score/play_cnt/cover 等；cell_view.has_more/next_offset。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 rank() 固定 selected_items=comic_series_rank；leaderboard_page 支持 all/human/comic/ai。

**静态证据**：[rank（原源码行2062）](evidence/hongguo.dis.txt)，证据文件第 18165 行；[leaderboard_page（原源码行2362）](evidence/hongguo.dis.txt)，证据文件第 20212 行。

##### `official.category` — 新剧、分类筛选面板、浏览流

`POST https://api5-normal-sinfonlinec.fqnovel.com/reading/distribution/category/landpage/v`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "filter_ids": "已展示 series_id 用英文逗号 join；feed_page 固定空串",
  "req_scene": "default | comic_series | ai_series",
  "offset": "integer，初始0，客户端按返回记录推进",
  "need_selector_panel": false,
  "limit": 18,
  "select_items": {
    "genre": [
      "short_play | comic_series | ai_series"
    ],
    "category_dim_theme": [],
    "category_dim_role": [],
    "category_dim_epoch": [],
    "sort": [
      "online_time | hot_score | hot_collect"
    ],
    "gender": [],
    "creation_status": [],
    "online_time": []
  },
  "session_id": "",
  "req_type": "only_content",
  "client_req_type": 3
}
```

**认证/头**：official_optional_signature：通用 query/session_headers；signed=SIGN_LIST，HG_SIGN_LIST 缺省为 false，可由环境设为 true。

**响应**：data.video_data[]（series_id/title/episode_cnt/score/play_cnt/cover/category_schema/video_desc/sub_title_list/vid 等）及 has_more；筛选面板模式消费 data.selector_rows[]。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：叠加 official_common_query（见公共协议）；以下只列业务附加字段。 4种调用变体：latest limit=18、sort=[online_time]，非短剧可 online_time=[days_7]；browse limit=18，8个 select_items 维度；feed_page limit=30；filters offset=0/limit=1/need_selector_panel=true/req_type=default，select_items 没有 creation_status，除 genre 外各项为空。

**静态证据**：[latest（原源码行2118）](evidence/hongguo.dis.txt)，证据文件第 18549 行；[filters（原源码行2226）](evidence/hongguo.dis.txt)，证据文件第 19185 行；[browse（原源码行2241）](evidence/hongguo.dis.txt)，证据文件第 19299 行；[feed_page（原源码行2303）](evidence/hongguo.dis.txt)，证据文件第 19758 行。

#### 公开网站备用与预览

##### `web.search` — 公开站搜索 SSR loader

`GET https://hongguoduanju.com/search/{urlencoded_keyword}`

**Query**：

```json
{
  "__loader": "search_(keyword)/page",
  "__ssrDirect": "true"
}
```

**Body**：无。

**认证/头**：未显式设置账号/token；网站 UA 为 Mozilla/5.0 (Linux; Android 12)。HTTPS 校验开启。SSR loader 禁止重定向，timeout=15 秒。

**响应**：首段 JSON object 的 searchList[]；video_data、series_id/keyword/series_title/name/series_status/episode_cnt/series_cover。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：关键词长度1–100，按 quote(..., safe="") 编码；客户端只 raw_decode 第一个 JSON 对象，后面可有 deferred 数据。

**静态证据**：[hgdj_search（原源码行1130）](evidence/offline_dl.dis.txt)，证据文件第 10125 行；[_hgdj_loader（原源码行1085）](evidence/offline_dl.dis.txt)，证据文件第 9768 行。

##### `web.player` — 剧目录及默认预览页 SSR loader

`GET https://hongguoduanju.com/player/{series_id}`

**Query**：

```json
{
  "__loader": "player_(series_id)/page",
  "__ssrDirect": "true"
}
```

**Body**：无。

**认证/头**：未显式设置账号/token；网站 UA 为 Mozilla/5.0 (Linux; Android 12)。HTTPS 校验开启。SSR loader 禁止重定向，timeout=15 秒。

**响应**：seriesDetail：series_id/series_name/series_intro/series_cover/episode_cnt/accessible_episode_cnt/vid_list 等；预览消费 video_player_info.main_url/poster_url/duration/width/height（在返回对象内查找）。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：网页目录可列出全部 vid，但预览会检查 accessible_episode_cnt。不能由目录数量推断每集已取得可播放 URL。

**静态证据**：[_hgdj_player_data（原源码行1056）](evidence/offline_dl.dis.txt)，证据文件第 9632 行；[_hgdj_listing（原源码行1180）](evidence/offline_dl.dis.txt)，证据文件第 10462 行；[hgdj_preview（原源码行1355）](evidence/offline_dl.dis.txt)，证据文件第 12068 行；[_hgdj_pv_episode（原源码行1336）](evidence/offline_dl.dis.txt)，证据文件第 11866 行。

##### `web.episode_player` — 指定剧集预览页 SSR loader

`GET https://hongguoduanju.com/player/{series_id}/{vid}`

**Query**：

```json
{
  "__loader": "player_(series_id)/(vid)/page",
  "__ssrDirect": "true"
}
```

**Body**：无。

**认证/头**：未显式设置账号/token；网站 UA 为 Mozilla/5.0 (Linux; Android 12)。HTTPS 校验开启。SSR loader 禁止重定向，timeout=15 秒。

**响应**：seriesDetail：series_id/series_name/series_intro/series_cover/episode_cnt/accessible_episode_cnt/vid_list 等；预览消费 video_player_info.main_url/poster_url/duration/width/height（在返回对象内查找）。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：网页目录可列出全部 vid，但预览会检查 accessible_episode_cnt。不能由目录数量推断每集已取得可播放 URL。

**静态证据**：[_hgdj_player_data（原源码行1056）](evidence/offline_dl.dis.txt)，证据文件第 9632 行；[_hgdj_listing（原源码行1180）](evidence/offline_dl.dis.txt)，证据文件第 10462 行；[hgdj_preview（原源码行1355）](evidence/offline_dl.dis.txt)，证据文件第 12068 行；[_hgdj_pv_episode（原源码行1336）](evidence/offline_dl.dis.txt)，证据文件第 11866 行。

##### `web.detail` — 网页详情补充总集数

`GET https://hongguoduanju.com/detail`

**Query**：

```json
{
  "series_id": "series_id"
}
```

**Body**：无。

**认证/头**：未显式设置账号/token；使用 _hgdj_session，网站 UA；timeout=15。

**响应**：HTML 文本，以“共 N 集”“全 N 集”“N 集全”正则提取数量；不是 JSON 业务 API。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_episodes（原源码行1015）](evidence/offline_dl.dis.txt)，证据文件第 9418 行；[_one（原源码行1032）](evidence/offline_dl.dis.txt)，证据文件第 45471 行。

##### `web.rank.ai` — AI网页榜单

`GET https://hongguoduanju.com/rank/hot-ai-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

##### `web.rank.human` — 真人网页榜单

`GET https://hongguoduanju.com/rank/hot-real-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

##### `web.rank.comic` — 漫剧网页榜单

`GET https://hongguoduanju.com/rank/hot-comic-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

#### 分享链接解析

##### `share.short` — 严格分享短链解析

`GET https://kylin.hainanyuyue.com | novelquickapp.com/s/{code}`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：无账号/token；User-Agent: Mozilla/5.0 (Linux; Android 12)。

**响应**：只读取状态码及 301/302/303/307/308 的 Location，解析 share 参数里的 series_id；不自动跟随此模式的跳转。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：code 满足 [A-Za-z0-9_-]{4,32}。输入只接受这两个规范 host；Location 的品牌域规则另外涉及 hainanyuyue.com / applink.novelquickapp.com。该规则来自客户端静态代码，未抓取链接。

**静态证据**：[_share_link（原源码行571）](evidence/offline_dl.dis.txt)，证据文件第 6092 行；[_share_read（原源码行756）](evidence/offline_dl.dis.txt)，证据文件第 7571 行；[_share_sid_from_location（原源码行722）](evidence/offline_dl.dis.txt)，证据文件第 7230 行；[_share_series_id（原源码行778）](evidence/offline_dl.dis.txt)，证据文件第 7739 行。

##### `share.public` — 其他公开分享页/分享榜单解析

`GET https://{user_supplied_public_host}{user_supplied_path_and_query}`

**Query**：

```json
{
  "dynamic": "原输入 URL 的查询参数，不添加固定 API 参数"
}
```

**Body**：无。

**认证/头**：无账号/token；Android UA；HttpsOnlySession，原 URL 和每次跳转均需公开 host 检查。

**响应**：HTML 或重定向最终 URL；_resolve_share_one 从 URL/前8000字符查找 video_series_id/video_id/series_id/book_id/material_id/content_id/vid；_scrape_board 从 window._SSR_DATA/_ROUTER_DATA 等解析系列。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：动态资源读取模板，不是发现了无限个固定业务 endpoint。不能把 HTML 内所有URL字符串都计为应用调用。

**静态证据**：[_public_get（原源码行700）](evidence/offline_dl.dis.txt)，证据文件第 7093 行；[_resolve_share_one（原源码行502）](evidence/offline_dl.dis.txt)，证据文件第 5803 行；[_scrape_board（原源码行464）](evidence/offline_dl.dis.txt)，证据文件第 5511 行。

#### 第三方 Catalog

##### `catalog.genres` — 目录分类标签

`GET https://explorer.hongguodownloader.com/genres`

**Query**：

```json
{
  "limit": 22
}
```

**Body**：无。

**认证/头**：前端 fetch 未加认证头或 credentials；cache=no-store。

**响应**：genres[]，每项至少 genre；检查 r.ok/j.error/genres 是否数组。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[downloader前端](evidence/downloader.inline.js)，证据文件第 305 行；[downloader前端](evidence/downloader.inline.js)，证据文件第 308 行。

##### `catalog.explorer` — 全量目录分页/搜索/筛选

`GET https://explorer.hongguodownloader.com/explorer`

**Query**：

```json
{
  "page": "从1开始，默认1",
  "size": 100,
  "sort": "newest | popular | eps",
  "genre": "可选非空分类",
  "status": "可选 completed | ongoing",
  "q": "可选关键词"
}
```

**Body**：无。

**认证/头**：前端 fetch 未加认证头或 credentials；cache=no-store。

**响应**：items[]、count、page、pages；items 交由 resultCards 使用 series_id/title/episode_cnt/score/cover/avail 等；HTTP429 或 error=rate_limited 单独提示繁忙。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：前端注释称 Cloudflare Worker/D1，但未检查服务端实现。后端 /dl/explorer 的 _explorer_catalog 是打包 explorer.json.gz 本地目录，不是该网络请求。

**静态证据**：[downloader前端](evidence/downloader.inline.js)，证据文件第 321 行；[downloader前端](evidence/downloader.inline.js)，证据文件第 332 行；[downloader前端](evidence/downloader.inline.js)，证据文件第 336 行。

#### 许可服务（Supabase RPC 形状）

##### `license.validate` — 验证许可

`POST https://api.hongguodownloader.com/rest/v1/rpc/validate_key`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "p_key": "<license_key>",
  "p_device": "<device_id>",
  "p_secure": true,
  "p_secret": "<device_secret_or_empty>"
}
```

**认证/头**：license_rpc：Content-Type=application/json，X-HG-Nonce=16随机字节的小写十六进制；若配置 anon key 则同时发 apikey 与 Authorization: Bearer <anon>。body 含 p_secure=true、p_secret=<当前设备 secret 或空值>。所有敏感值省略。

**响应**：ok/reason/expires_at；_apply_result 也处理 device_secret（若有）。active 是客户端由 ok 派生的本地状态。

**用途和副作用**：验证并刷新本地许可状态/离线宽限缓存；若 reason=needs_reactivate，客户端会再调用 activate_key，故整条刷新流程可能导致远端激活。

**调用细节**：默认打包 host 固定为 api.hongguodownloader.com；开发模式才允许 SUPABASE_URL / supabase.json.url 覆盖。响应认证公共说明见下方。

**静态证据**：[_refresh（原源码行586）](evidence/licensing.dis.txt)，证据文件第 4023 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行；[_secure_args（原源码行316）](evidence/licensing.dis.txt)，证据文件第 2117 行。

##### `license.activate` — 激活/重新绑定许可

`POST https://api.hongguodownloader.com/rest/v1/rpc/activate_key`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "p_key": "<license_key>",
  "p_device": "<device_id>",
  "p_device_label": "<用户计算机标识>",
  "p_secure": true,
  "p_secret": "<device_secret_or_empty>"
}
```

**认证/头**：license_rpc：Content-Type=application/json，X-HG-Nonce=16随机字节的小写十六进制；若配置 anon key 则同时发 apikey 与 Authorization: Bearer <anon>。body 含 p_secure=true、p_secret=<当前设备 secret 或空值>。所有敏感值省略。

**响应**：ok/reason/expires_at/device_secret；响应经签名验证后应用；secret保存到本地受保护存储，不返回给UI。UI active 字段由客户端计算。

**用途和副作用**：修改远端许可证设备绑定；保存/更新本地许可密钥和设备secret；本次未调用。

**调用细节**：默认打包 host 固定为 api.hongguodownloader.com；开发模式才允许 SUPABASE_URL / supabase.json.url 覆盖。响应认证公共说明见下方。

**静态证据**：[activate（原源码行634）](evidence/licensing.dis.txt)，证据文件第 4407 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行；[_secure_args（原源码行316）](evidence/licensing.dis.txt)，证据文件第 2117 行。

##### `license.deactivate` — 停用本机许可

`POST https://api.hongguodownloader.com/rest/v1/rpc/deactivate_key`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "p_key": "<license_key>",
  "p_device": "<device_id>",
  "p_secure": true,
  "p_secret": "<device_secret_or_empty>"
}
```

**认证/头**：license_rpc：Content-Type=application/json，X-HG-Nonce=16随机字节的小写十六进制；若配置 anon key 则同时发 apikey 与 Authorization: Bearer <anon>。body 含 p_secure=true、p_secret=<当前设备 secret 或空值>。所有敏感值省略。

**响应**：ok/reason/next_move_allowed_at/cooldown_until 等；not_found/not_bound_here/revoked 也可触发本地清理。

**用途和副作用**：解除或修改远端设备绑定并清理本地许可/secret/宽限状态；本次未调用。

**调用细节**：默认打包 host 固定为 api.hongguodownloader.com；开发模式才允许 SUPABASE_URL / supabase.json.url 覆盖。响应认证公共说明见下方。

**静态证据**：[deactivate（原源码行660）](evidence/licensing.dis.txt)，证据文件第 4617 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行；[_secure_args（原源码行316）](evidence/licensing.dis.txt)，证据文件第 2117 行。

##### `license.download_check` — 免费额度/下载准入

`POST https://api.hongguodownloader.com/rest/v1/rpc/check_download`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "p_device": "<device_id>",
  "p_series": "series_id string",
  "p_secure": true,
  "p_secret": "<device_secret_or_empty>"
}
```

**认证/头**：license_rpc：Content-Type=application/json，X-HG-Nonce=16随机字节的小写十六进制；若配置 anon key 则同时发 apikey 与 Authorization: Bearer <anon>。body 含 p_secure=true、p_secret=<当前设备 secret 或空值>。所有敏感值省略。

**响应**：allowed/licensed/unlimited/reason/free_limit/free_used/remaining 等（按使用方消费）。

**用途和副作用**：下载前的计数/准入RPC，可能登记剧或消耗免费额度，不能当成无副作用探测；服务端计数实现未知，本次未调用。

**调用细节**：默认打包 host 固定为 api.hongguodownloader.com；开发模式才允许 SUPABASE_URL / supabase.json.url 覆盖。响应认证公共说明见下方。

**静态证据**：[check_download（原源码行706）](evidence/licensing.dis.txt)，证据文件第 5029 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行；[_secure_args（原源码行316）](evidence/licensing.dis.txt)，证据文件第 2117 行。

##### `license.usage` — 额度与订阅状态

`POST https://api.hongguodownloader.com/rest/v1/rpc/usage_status`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "p_device": "<device_id>",
  "p_key": "<license_key，仅本地已有key时添加>",
  "p_secure": true,
  "p_secret": "<device_secret_or_empty>"
}
```

**认证/头**：license_rpc：Content-Type=application/json，X-HG-Nonce=16随机字节的小写十六进制；若配置 anon key 则同时发 apikey 与 Authorization: Bearer <anon>。body 含 p_secure=true、p_secret=<当前设备 secret 或空值>。所有敏感值省略。

**响应**：licensed/free_limit/free_used/remaining/plan/expires_at/max_devices/devices_used/device_count/has_key/reason/blocked_reason。

**用途和副作用**：查询额度并刷新本地usage缓存；服务端内部副作用未知。

**调用细节**：默认打包 host 固定为 api.hongguodownloader.com；开发模式才允许 SUPABASE_URL / supabase.json.url 覆盖。响应认证公共说明见下方。

**静态证据**：[_fetch_usage（原源码行761）](evidence/licensing.dis.txt)，证据文件第 5474 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行；[_secure_args（原源码行316）](evidence/licensing.dis.txt)，证据文件第 2117 行。

#### 支付与账单

##### `pay.plans` — 购买套餐列表

`GET https://pay.hongguodownloader.com/plans`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：调用端未添加特殊 auth header；HTTPS-only session。打包版本固定 host，开发模式 HG_PAY_URL 可覆盖。

**响应**：返回 JSON；UI消费 plans[]，id/title/usd/interval/blurb/badge；失败回退缓存/空plans。

**用途和副作用**：读取套餐；缓存600秒。

**静态证据**：[dl_license_plans（原源码行3022）](evidence/server.dis.txt)，证据文件第 24002 行。

##### `pay.checkout` — 创建结账会话

`POST https://pay.hongguodownloader.com/create-checkout`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "plan": "month | year | life"
}
```

**认证/头**：调用端未添加特殊 auth header；HTTPS-only session。打包版本固定 host，开发模式 HG_PAY_URL 可覆盖。

**响应**：url、session_id；缺失会话或不安全url被拒绝。

**用途和副作用**：创建远端结账会话；客户端会打开返回的支付页面。可能进入付费流程，本次未调用。

**静态证据**：[dl_license_buy（原源码行3040）](evidence/server.dis.txt)，证据文件第 24137 行。

##### `pay.key` — 查询购买结果并取许可密钥

`GET https://pay.hongguodownloader.com/key`

**Query**：

```json
{
  "session_id": "<checkout_session_id>"
}
```

**Body**：无。

**认证/头**：调用端未添加特殊 auth header；HTTPS-only session。打包版本固定 host，开发模式 HG_PAY_URL 可覆盖。 session_id 是结果查询凭据。

**响应**：未就绪时 reason；就绪时 key=<license_key>。本地处理随后调用 LIC.activate(key)，并生成 pending/ok/activated/reason/usage 的UI响应。

**用途和副作用**：取回新购许可；客户端收到 key 会自动触发 activate_key，整条调用链含设备绑定副作用。本次未调用。

**静态证据**：[dl_license_purchase_poll（原源码行3067）](evidence/server.dis.txt)，证据文件第 24374 行。

##### `pay.portal` — 账单管理入口

`POST https://pay.hongguodownloader.com/portal`

**Query**：无额外业务查询字段。

**JSON body**：

```json
{
  "key": "<license_key>",
  "device": "<device_id>"
}
```

**认证/头**：调用端未添加特殊 auth header；HTTPS-only session。打包版本固定 host，开发模式 HG_PAY_URL 可覆盖。 body中的许可key/device用于查找归属。

**响应**：ok/url/reason；无url或ok=false时拒绝。

**用途和副作用**：创建或获取账单管理会话，随后浏览器打开返回URL；后续用户操作可影响订阅。本次未调用。

**静态证据**：[dl_license_manage（原源码行3088）](evidence/server.dis.txt)，证据文件第 24562 行。

#### 版本更新

##### `update.release` — 最新版本元数据

`GET https://api.github.com/repos/M4St3r0/hongguo-downloader/releases/latest`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：Accept: application/vnd.github+json；User-Agent: HongguoDownloader；若HG_GITHUB_TOKEN非空，附 Authorization: Bearer <token>。

**响应**：tag_name（回退version）、html_url（回退url）、assets[].name/browser_download_url、body（回退notes）。选择首个.exe附件；版本比较后生成UI update结果。

**用途和副作用**：读取版本，缓存1800秒。

**静态证据**：[dl_update_check（原源码行3121）](evidence/server.dis.txt)，证据文件第 24822 行。

##### `update.installer` — 下载更新安装包

`GET https://github.com/M4St3r0/hongguo-downloader/releases/download/{tag}/{installer_name.exe}`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：HttpsOnlySession；此下载调用没有复用GitHub API的Bearer头。

**响应**：二进制安装文件，Content-Length可用于进度；客户端计算SHA-256并通过Windows Authenticode检查签名/发布者。

**用途和副作用**：写入本地 update/HongguoDownloader-Setup.exe；此请求本身不执行安装，/dl/update-run另行触发本地执行。本次未调用。

**调用细节**：URL来自release assets并通过固定github.com仓库前缀与.exe检查；服务端可能重定向到动态下载资源，不从字符串猜测新API。

**静态证据**：[dl_update_download（原源码行3161）](evidence/server.dis.txt)，证据文件第 25200 行。

#### 可配置签名辅助服务

##### `signer.grab` — 刷新抓取到的App会话

`GET {SIGN_SERVER_base}/grab`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：可选 X-Sign-Token: <HG_SIGN_TOKEN>。

**响应**：url 与 headers，或 error。解析 URL query：仅更新config已有且不在DEVICE_KEYS集合内的字段；headers只提取cookie/x-tt-token/x-tt-store-region/x-tt-store-region-src。

**用途和副作用**：可能触发签名服务端抓取会话，随后修改本地config.json；仅第一个SIGN_SERVER，20秒刷新节流。本次未调用。

**调用细节**：base来自逗号分隔SIGN_SERVER环境变量，可能是127.0.0.1，也可能用户配置远端；不是固定外部域名。Jar是否实现/grab须看签名器文档。

**静态证据**：[refresh_session（原源码行437）](evidence/hongguo.dis.txt)，证据文件第 4955 行。

##### `signer.health` — 签名后端状态汇总

`GET {SIGN_SERVER_base}/`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：此stats()调用未附加X-Sign-Token；入口本地/stats先检查admin_token。

**响应**：ready、pid；请求失败汇总error。

**用途和副作用**：读取签名服务状态。

**调用细节**：host是否外部由SIGN_SERVER配置决定；/sign协议另见主API文档。

**静态证据**：[stats（原源码行737）](evidence/server.dis.txt)，证据文件第 7320 行。

#### 媒体传输（非业务 JSON API）

##### `media.video` — 视频资源下载与Range续传

`GET https://{host_from_main_url_or_backup_url}{path_and_query_from_video_model}`

**Query**：

```json
{
  "dynamic": "完整保留模型main_url/backup_url的签名和有效期参数"
}
```

**Body**：无。

**认证/头**：模型返回URL可自带临时签名；视频传输不重新附加业务API签名。支持 Range: bytes=0-0 探测、Range: bytes={start}-{end} 分段/续传。

**响应**：200全文件或206分段；Content-Length/Content-Range/ETag/Accept-Ranges；响应为媒体字节而非JSON。

**用途和副作用**：拉取媒体字节并写本地文件；有流量消耗。

**调用细节**：不把封面/图片CDN地址当API；此项仅为搜索→最终视频资源传输链的动态模板。

**静态证据**：[_probe（原源码行41）](evidence/downloader.dis.txt)，证据文件第 399 行；[_download_segmented（原源码行57）](evidence/downloader.dis.txt)，证据文件第 597 行；[download_file（原源码行2491）](evidence/hongguo.dis.txt)，证据文件第 21311 行；[run（原源码行2905）](evidence/hongguo.dis.txt)，证据文件第 28866 行；[_range_get（原源码行3514）](evidence/hongguo.dis.txt)，证据文件第 34325 行。

### 3. 榜单参数映射

| category | selected_items | recommend | hot | new |
|---|---|---|---|---|
| all | all | ranklist_hot_sc | ranklist_hot_play_sc | ranklist_new_rank_sc |
| human | human | human_hot_sc | human_hot_play | human_new_rank |
| comic | comic_series_rank | comic_series_hot_rank | comic_series_hot_play | comic_series_new_rank |
| ai | ai_playlet | ai_playlet_hot_sc | ai_playlet_hot_play | ai_playlet_new_rank |

最后三列是 `sub_selected_items`。映射在 `hongguo.py` 原源码 2352–2359 行；反汇编 [hongguo.dis.txt](evidence/hongguo.dis.txt) 第 2133 行附近。旧 `rank()` helper 固定漫剧榜。

### 4. 许可响应认证与支付边界

许可 RPC 统一 `POST /rest/v1/rpc/{fn}`，这是 Supabase/PostgREST 形状，但打包程序默认调用自有域 `api.hongguodownloader.com`，不直接由此证明后端部署细节。开发模式可从环境或 supabase.json 改 base。

每次请求生成 nonce。响应读取 `X-HG-Ts`、`X-HG-Sig`、`X-HG-Kid`，按本地公钥验证由 `ts + "." + nonce + "." + device + "."` 的 UTF-8 字节与原始 body 拼成的消息；打包版对无法验证的响应拒绝处理。这里只记录协议形状，不提供密钥/secret，也没有调用激活/解绑/额度计数。

许可安全协议证据：[_sig_message（原源码行177）](evidence/licensing.dis.txt)，证据文件第 1044 行；[_verify_msg（原源码行184）](evidence/licensing.dis.txt)，证据文件第 1097 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行。

付款接口返回的URL由 `_safe_pay_url()` 检查：HTTPS且命中 checkout.stripe.com、billing.stripe.com、hongguodownloader.com（含程序允许的子域规则），随后 `webbrowser.open()`。安装包内没有据此观察到对 Stripe REST API 的直接调用；浏览器进入页面后的网络协议不在此安装包静态证据范围。

### 5. 不应误算为远端业务 API 的项目

| 项目 | 证据结论 |
|---|---|
| `/dl/bugreport` | 本地创建 `bugreports/bugreport-时间.zip`，写 about.txt/app-log.txt，可选截图；打开本地文件夹。前端另打开 Telegram 支持链接，无自动上传证据。 |
| `_explorer_catalog()` | 读取本地 `web/explorer.json.gz`；不同于前端两条 explorer.hongguodownloader.com 请求。 |
| `/reading/bookapi/search/page/v/?query=probe&aid=8662` | app._sign_probe_once 与 server.dl_diag 把该URL作为签名输入；未把它作为外部 HTTP 请求发送。 |
| 图片/海报/头像CDN | downloader、hongguo.download_image、server.api_img 会GET图片资源；不是独立 JSON API，不按每张封面URL计数。 |
| 官网/Telegram支持链接 | 浏览器导航；未看到客户支持上传API。 |
| `apikeys.pyc` | 本地生成/保存/撤销访问本地API的key，没有独立外网HTTP调用。 |
| `devicepool.pyc` | 本地加载/生成设备参数并轮换；没有设备注册HTTP调用。 |
| `nettls.pyc` | 通用HTTPS/证书/重定向传输封装；没有固定业务URL。 |
| `app.pyc`、`launcher.pyc` | 进程与本地端口控制；localhost探测归本地API文档。 |

对应证据：[dl_bugreport（原源码行2245）](evidence/server.dis.txt)，证据文件第 18849 行；[_explorer_catalog（原源码行1380）](evidence/server.dis.txt)，证据文件第 12777 行；[_sign_probe_once（原源码行72）](evidence/app.dis.txt)，证据文件第 1608 行；[dl_diag（原源码行1608）](evidence/server.dis.txt)，证据文件第 14251 行；[前端报告按钮](evidence/downloader.inline.js) 第2303–2315行。

### 6. 覆盖范围与剩余未知

已静态扫描上述10个pyc的递归code object URL/path常量，并沿请求发送函数核对每个固定路径及动态URL读取调用；增加检查打包HTML/JS直接 fetch，因此包含不经Python后端的Catalog请求。机器清单带每个被审阅工件SHA-256与函数/原源码行/反汇编行。

此处完整指**该构建调用端可见路由范围**。远端服务可能还有本程序没有调用的endpoint；服务端严格必填字段、全部错误码、限流规则与隐藏副作用无法仅凭客户端证明。动态配置SIGN_SERVER/开发模式host/分享URL/CDN URL只能记录模板。

没有执行原pyc模块，没有新增访问许可/支付/更新/报告接口，也没有把静态函数存在性描述成运行时调用事实。核心导出脚本的实测结果见此前生成的请求轨迹和 live-verification.json。


<a id="video-encryption"></a>

## 四、视频加密与下载后处理

**当前导出样本确实有加密，取得下载 URL 不等于取得可直接播放的视频。** 本地《逆袭之实习教出金牌班，家长要换班主任》111 集共 555 条、《坠崖捡个参娃娃》74 集共 370 条清晰度记录，均返回 `encrypt_info.encrypt=true`、`encryption_method="cenc-aes-ctr"`。后者第一集的 1080p、720p、540p、480p、360p 五档还确认带有 `spade_a`。目前脚本只导出 URL 和模型信息，尚未执行原程序的解密、封装修复步骤。[脱敏观察记录](evidence/video-encryption-observation.json)

最初的结论来自已导出模型和安装器字节码。随后按用户要求，已实际下载并解密《坠崖捡个参娃娃》第 1 集，结果见下节；没有检查用户另行下载的文件，因此不把加密当作所有播放失败的唯一可能原因。

### 单集实际解密验证（2026-10-12）

已生成 [第 1 集 1080p 可播放 MP4](../outputs/decrypted-sample/坠崖捡个参娃娃_第01集_1080p.mp4)：1080×1920，时长 123.344 秒，HEVC 视频和双声道 AAC 音频，文件大小 10,680,289 字节。

- 加密原文件保留为同目录 `.enc.mp4`，10,731,638 字节，MD5 与视频模型 `file_hash` 一致。
- 在工作区独立 `.venv-decrypt` 环境中使用 Python 3.11.17、PyCryptodome 3.23.0，调用安装包原始 `unwrap_spade`、`oracle`、`decutil` 模块；执行前校验模块 SHA-256 与安装器清单一致。
- 密钥与文件匹配校验通过；3700/3700 视频样本 NAL 结构有效，2660 个音频样本已解密；FFmpeg 流复制重封装成功。
- 用 FFmpeg `-xerror` 对输出的完整视频、音轨进行解码，退出码 0、stderr 为空，处理至第 3700 帧并正常结束。此项是实际解码验证，不是仅检测 MP4 文件头。
- 未进行重新编码，未使用外部密钥服务，未把内容密钥写进命令行或验证记录。

验证记录：[decryption-verification.json](../outputs/decrypted-sample/decryption-verification.json)。执行脚本：[download_sample.py](tools/download_sample.py)、[decrypt_sample.py](tools/decrypt_sample.py)。它们固定用于这份单集样本；主入口 `hongguo.py` 仍只负责信息和地址导出。

### 原程序的处理流程

| 步骤 | 程序实际行为 | 静态证据 |
|---|---|---|
| 取得模型、选择清晰度 | `H.get_video_tracks` 返回视频轨道；`_pick_track` 选择轨道，再读取该轨道的 `encrypt_info`、`video_meta` 和 `main_url`。 | `offline_dl.py:1669–1674`；[反汇编](evidence/offline_dl.dis.txt:15031) |
| 下载 | `encrypt` 为假则直接下载为最终 `.mp4`；为真则先下载到 `.enc.mp4`，同时把期望的文件大小及文件 hash 传入下载层。 | `offline_dl.py:1680–1685`；[反汇编](evidence/offline_dl.dis.txt:15152) |
| 得到内容密钥 | 将 **对应轨道** 的 `spade_a` 交给本地 `spade_to_key`：先 Base64 解码，再运行随包的 `unwrap_v1` 字节运算。输出须是 32 个十六进制字符，即 16 字节 AES 密钥。默认模式失败于格式检查时尝试另一模式；这里没有向远端服务请求密钥。`kid` 是标识字段，不是直接拿来当 AES key。 | `unwrap_spade.py:38,90–92`；[反汇编](evidence/unwrap_spade.dis.txt:745)。`offline_decrypt.py:28–36`；[反汇编](evidence/offline_decrypt.dis.txt:319) |
| 校验模型与文件是否匹配 | 从 MP4 的 `senc` 找到 8 字节 IV 候选；用本地 `oracle.verify_key_iv` 检查解密后的视频样本长度结构。它先检查首块，再要求前两个样本通过 NAL 长度检查；不匹配则返回失败。 | `offline_decrypt.py:40–50`；[反汇编](evidence/offline_decrypt.dis.txt:443)。`oracle.py:66–97`；[反汇编](evidence/oracle.dis.txt:1121) |
| 解密音视频样本 | 找 `moov/trak` 中的视频与音频轨道，利用 `stsz`、`stsc`、`stco/co64` 计算样本位置和长度；各轨道使用自己的 `senc` 基础 IV，对每个样本的字节范围执行 AES-128-CTR，写入 `.raw.mp4`。 | `oracle.py:28–54`；[反汇编](evidence/oracle.dis.txt:526)。`decutil.py:65–99`；[反汇编](evidence/decutil.dis.txt:799) |
| 修复 MP4 封装 | 优先 FFmpeg **流复制重封装**（`-c copy`，视频标记 `hvc1`），不是重新编码。没有 FFmpeg 或其正常返回失败时，尝试纯 Python 将 `encv/enca` 改成 `hvc1/mp4a`，并将 `sinf/senc/saiz/saio` 等加密描述盒改成 `free`。成功后清理临时文件，保留最终 `.mp4`。 | `decutil.py:102–185`；[反汇编](evidence/decutil.dis.txt:1263)。`offline_dl.py:1688–1698`；[反汇编](evidence/offline_dl.dis.txt:15233) |

### 加密在哪里

**不是把整个 MP4 文件作为一个 AES 数据块解密。** 原程序仍然直接读取 MP4 的目录和样本表，只改写样本表指定的视频/音频数据区，也就是媒体负载中的对应样本。它对每个样本完整范围执行 CTR 运算；没有在这个解密路径中实现通用的“一个样本内部部分明文、部分密文”子样本表处理。

每条轨道有自己的基础 IV，每个样本重新建立 CTR 状态，并随样本序号递增。故不能简单把 `.mp4` 改名、对整个文件执行一次 AES、或只用 FFmpeg 改封装来代替内容解密。加密内容解开后，容器中仍可能保留“此轨道已加密”的标记，所以原程序还专门做了最后的封装修复。[`_decrypt_track`](evidence/decutil.dis.txt:799)、[`strip_cenc`](evidence/decutil.dis.txt:1263)

### 是否离线，Mac 需要什么

拿到匹配的 `spade_a` 和完整加密文件后，这条解密路径是本地运算。`oracle` 的名字不代表在线密钥服务：这里调用的是本地解析与验证函数；同模块中的 ADB/设备内存分析工具没有被该解密调用链执行。目录名叫 `frida` 也不代表正常离线解密必须连接手机或启动 Frida。

主要依赖是 Python、提供 `Crypto.Cipher.AES` / `Crypto.Util.Counter` 的 PyCryptodome，以及可选的本机 FFmpeg。安装器清单包含 PyCryptodome 3.23.0；FFmpeg 查找函数区分 Windows 的 `.exe` 和其他平台的可执行文件，并会搜索 PATH，因此核心实现没有必须调用 Windows 加密 API 的证据。[FFmpeg 查找逻辑](evidence/decutil.dis.txt:158)

最初本机检查结果：macOS ARM64，主项目虚拟环境 Python **3.14.3**，其中**未发现 `Crypto` 模块**；PATH 中已有 `/opt/homebrew/bin/ffmpeg` 和 `ffprobe`。随安装器提取的 Python 字节码是 **CPython 3.11** 格式，不能直接作为 3.14 环境的模块导入。[初始环境记录](evidence/video-encryption-observation.json)

单集验证已另建 `.venv-decrypt`（Python 3.11.17 + PyCryptodome 3.23.0），运行时保存在工作区 `.runtime/python`，没有替换系统 Python 或主导出脚本环境。

### 已知限制

这套代码针对它支持的 `unwrap_v1` 与 MP4 布局，不足以证明支持所有加密版本。源码里的“可能是 ver2/AES-GCM”是失败提示，不能据此认定某次失败一定属于该算法。当前样本元数据明确声明的是 `cenc-aes-ctr`。

最终验证主要是视频样本的 NAL 长度结构统计；音频记录已解密样本数，默认流程没有做完整音视频解码回放测试。部分视频样本校验异常时原程序还可能返回产物并警告。另有 `bytevc2` 编码兼容性警告分支，因此“解密完成”与“所有播放器均可播放”也不是同一项保证。本次所查第一集模型的编码字段是 `bytevc1`。[校验逻辑](evidence/offline_decrypt.dis.txt:558)、[编码兼容分支](evidence/offline_dl.dis.txt:15081)

文档和验证记录不包含实际内容密钥或 `spade_a` 值。


