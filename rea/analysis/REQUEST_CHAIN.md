# HongguoDownloader：搜索 → 选剧 → 剧信息 → 每集地址

本报告针对 `HongguoDownloader-Setup.exe` 中提取的程序，描述能从静态代码证明的请求协议。核心链路已经确定：**关键词搜索得到 `series_id`，详情接口把 `series_id` 展开为集数与 `vid`，视频模型接口把各个 `vid` 展开为媒体 URL**。APP 接口依赖本地签名服务；另有无需该签名服务的网页 SSR 备用链路，但网页可播放集数受 `accessible_episode_cnt` 限制。

## 证据范围与 REA 使用情况

- 安装包 SHA-256：`9d77a2548cc1bde92c4a269a3f482655b4f5fc538421f328af8d959d6739b592`。
- 使用了 REA / rea-agents 工具分析。安装包 inspect 证据 ID：`ev_f5225a99baecc841e43a6e8e6ec577d9d2b544ace6665f3ed2cc100fa1210bf5`。
- 提取 HTML 中的 inline JavaScript 另行交给 REA 分析，其 parent 证据 ID：`ev_998632b9087e65138696a406815db5bec0be9dcb85010d8fe2ea0d70b1ac8fa2`。
- 提取物在 [extracted](extracted/)，Python 3.11 字节码用 `xdis` 只读反汇编，Java 类用 `javap` 只读检查。REA 本身没有 Python 字节码反编译能力，不能把这些辅助工具的结果称作 REA 反编译结果。
- **未运行原 Windows EXE，也未导入执行提取出的 Python 模块。** 下文的“原程序行为”均指反汇编证明的实现，不等于已对原 EXE 做过抓包。现有 HTTP 探测文件单独列作实测证据。

下文引用的 `文件:行号` 为本目录中反汇编文本的物理行号。文本内部的 `First Line` 和 `991:` 等是原 `.py` 的源代码行号，两者不要混用。

## 1. 从界面操作到后端函数

| 用户操作 | 浏览器到本地服务 | 本地处理 | 接下来可能发出的远端请求 |
|---|---|---|---|
| 输入关键词 | `GET /dl/search?q=关键词` | `server.dl_search` → `hongguo.search_series` → `_search_page` | 签名请求，再调用 APP 搜索接口；签名源慢或不可用时有网页备用搜索 |
| 搜索尚未完成时重试 | `GET /dl/search?q=关键词&again=1` | 等待/读取已有异步搜索任务 | 不保证每次浏览器轮询都对应新远端请求 |
| 点击更多结果 | `GET /dl/search?q=关键词&cursor=...` | 服务端保存的分页状态 | 下一页 APP 搜索请求，带 `offset/passback/search_id` |
| 补充系列/续季信息 | `GET /dl/search/seasons?q=关键词` | 续季聚合结果 | 是辅助结果补充，不是获得选中剧每集 URL 的必要步骤 |
| 选剧、打开选集 | `GET /dl/episodes?series_id=...` | `hongguo.get_episodes` | 签名请求，再调用 APP 剧详情接口 |
| 点击原软件下载 | `POST /dl/submit` | 接收 `series_ids/ranges/scores/settings`，启动 `_dl_worker` 与 `offline_dl.download_series` | 列表、视频模型及后续 CDN 请求 |

界面请求证据：[搜索](evidence/downloader.inline.js#L372)、[重试](evidence/downloader.inline.js#L402)、[分页](evidence/downloader.inline.js#L536)、[续季](evidence/downloader.inline.js#L492)、[选集](evidence/downloader.inline.js#L894)、[提交下载](evidence/downloader.inline.js#L852)。后端证据：`server.dis.txt:12031`（`dl_search`，原源行 1286）、`:13278`（`dl_episodes`，原源行 1437）、`:11345`（`dl_submit`，原源行 1204）、`:10201`（`_dl_worker`，原源行 1077）。

`/dl/episodes` 只给界面返回 `series_id/title/cover/total/episodes`，其中 `episodes` 是排序、去重后的集序号。它不是完整详情接口。原本地服务另外注册了 `GET /episodes?series_id=...`，返回 `{meta, episodes}`；还注册了 `GET /video_url?vid=...`，返回选中的媒体地址。这两个路径没有 `/api` 前缀。证据：`server.dis.txt:1580`、`:1683`、`:9007`、`:9635`。

## 2. APP 请求的共同构造规则

主机来自 [config.json](extracted/app/config.json)：当前安装包配置为 `api5-normal-sinfonlinec.fqnovel.com`。基础 query 标识的是 `aid=8662`、`app_name=novelread`、`version_name=7.2.9.32`、Android 设备环境；并非从软件名字推断的另一个红果 APP 协议。

构造顺序如下：

1. 复制配置的 `base_query`，如设备池启用则覆盖当前设备 query。
2. 合并接口自己的 query。
3. 添加毫秒时间戳 `_rticket`。
4. 构造完整 `https://{host}{path}?{query}`。
5. 有 JSON body 时使用 `json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')`。签名与真实发送必须使用同一份字节。
6. 复制 `session_headers`，设置 `content-type: application/json; charset=utf-8`。有 body 时，增加 `x-ss-stub = MD5(body_bytes).hexdigest().upper()`。
7. 向签名器提交完整 URL 和待签 headers，把返回对象合并回 headers，然后发送真实平台请求。

证据：`hongguo.dis.txt:5449`（`build_url`，源行 482）、`:5570`（`_req_headers`，源行 494）、`:5684`（`_api_once`，源行 510）。`api` 的默认 `signed=True` 见 `hongguo.dis.txt:1309` 和 `:5954`。

基础 query 与请求头应作为配置输入，不能用一个过时签名永久复用；设备字段、时间戳、完整 URL 或 POST body 改动都会使“先签名后发送同一请求”的前提发生变化。原程序还会轮换设备、限速、重试和缓存，因此实际请求次数受缓存与失败状态影响。

## 3. 请求 S：签名服务

每一个需要签名的平台请求，前面都有一次独立的本地签名 HTTP 请求：

```http
POST http://127.0.0.1:<sign_port>/sign
Content-Type: application/json
X-Sign-Token: <HG_SIGN_TOKEN，如进程配置了该变量>
```

```json
{
  "url": "https://api5-normal-sinfonlinec.fqnovel.com/<平台路径>?<全部参数>",
  "headers": {
    "user-agent": "<config.session_headers 中的值>",
    "content-type": "application/json; charset=utf-8",
    "x-ss-stub": "<仅 POST body 存在时的 MD5 大写十六进制>"
  }
}
```

返回 JSON 是需要并入真实请求的 header 字典；若含 `error`，Python 调用方抛错。`X-Sign-Token` 用于保护**签名服务自身**，并不是发给视频平台的账号 token。证据：`hongguo.dis.txt:3114`（`_sign_auth_headers`）、`:4390`（`_sign_post_once`）、`:5827` 附近（合并签名返回值）。

本地签名器不是网上硬编码的签名 API。`app.pyc` 默认 `HG_SIGN_PORT=9099`（端口冲突时可重新选择），设置 `SIGN_SERVER=http://127.0.0.1:<port>` 与 `HG_SIGN_TOKEN`，再从 `app/sign` 启动：

```text
javaw.exe -Xmx1024m -XX:+ExitOnOutOfMemoryError
  --add-opens java.base/java.lang=ALL-UNNAMED
  -cp unidbg-sign.jar com.hongguo.sign.FqTrace serve <port>
```

这是静态还原的 Windows 启动命令，不是本报告声称已执行的命令。证据：`app.dis.txt:439`（端口默认值）、`:8289`（启动函数）、`:12377`（环境变量）；`launcher.dis.txt:1161`、`:1249` 有对应控制台启动链。

Java 实现使用 unidbg，读取 `../capture/fq_oversea/libmetasec_ml.so` 与 `../capture/fq_oversea/ms_16777218.bin`，默认绑定 `127.0.0.1`，注册 `/sign`。设置了 `HG_SIGN_TOKEN` 时，不匹配的 `X-Sign-Token` 返回 HTTP 401 和 `{"error":"unauthorized"}`。证据：`FqTrace.javap.txt:34`、`:837`、`:1048`。这里证明的是服务协议与依赖，不宣称已经还原底层签名算法。

## 4. 请求 A：关键词搜索

```http
GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/search/tab/v
    ?<base_query>&_rticket=<毫秒时间戳>
    &query=<关键词>&tab_name=feed&search_source=1
    &offset=0&count=0&use_correct=true
```

本接口无请求体，先走请求 S，再发送带签名的 GET。注意 `count=0` 是原字节码中的真实值，不能自行替换为“请求 0 条结果”的语义。

搜索结果位置是 `response.search_tabs[0].data`。每个 cell 的 `book_id`，或缺失时的 `search_result_id`，被当作后续 `series_id`。标题和元信息可能分布在 `video_detail`、`video_data`、高亮字段等位置，所以不能仅对顶层 `title` 做机械读取。原解析器整理的结果包括：

```text
series_id, title, episode_cnt, score, play_cnt, hot,
copyright, cover, intro, vid, duration, horiz_cover, cover_tags
```

分页取 `search_tabs[0].next_offset/passback/search_id/has_more`，下一次请求把 `offset` 更新，并在非空时带回 `passback/search_id`。浏览器拿到的 `cursor` 是本地服务的分页凭据，不能直接当平台的 `passback` 使用。

证据：`hongguo.dis.txt:9139`（`search`，源行 991）、`:13452`（界面使用的 `_search_page`，源行 1515）、`:8724`（`_parse_search_cell`，源行 940）。旧 `search` 包装器默认最多 20 个结果、至多 12 页，最大结果上限 40；这不是平台全部剧目的数量。

用户选中一行后，下一步只需保留其 `series_id`，不需要靠剧名再次猜匹配。

## 5. 请求 B：完整剧详情与集列表

```http
POST https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_detail/v1/?<base_query>&_rticket=...
```

请求体：

```json
{
  "biz_param": {
    "detail_page_version": 0,
    "disable_digg_stat": false,
    "disable_video_relate_book": false,
    "image_shrink_datas_str": "<IMAGE_SHRINK 常量>",
    "need_all_video_definition": false,
    "need_mp4_align": false,
    "screen_width_px": "900",
    "source": 7,
    "use_os_player": false,
    "use_server_dns": false
  },
  "series_id": "<选中剧的 series_id>"
}
```

`IMAGE_SHRINK` 是安装包中的固定 Base64 字符串，编码两个图像缩放对象；保留原值与其中换行即可复现 body。原值位于 `hongguo.dis.txt:1030`。请求体结构证据：`hongguo.dis.txt:9620`（`_episodes_body`，源行 1053）。

响应取值链为：

```text
response.data[str(series_id)].video_data
  ├─ series_title / series_intro / episode_cnt / series_status / ...
  └─ video_list[]
       ├─ vid_index  → 第几集
       ├─ vid        → 请求视频地址的关键 ID
       ├─ title / duration / episode_cover
       └─ comment_count / digged_count
```

原程序整理的剧元信息是 `series_id/title/intro/episode_cnt/status/play_cnt/followed_cnt/create_time/cover/score/category/celebrities/album_id/season_no/novel_id`。集列表按合法 `vid_index` 排序，集标题在界面模型中裁为 30 字符。为满足“全部剧信息”，脚本应同时保存原始 `video_data` 与整理字段，避免界面模型的截断和字段筛选丢信息。

证据：`hongguo.dis.txt:10641`（`get_episodes`，源行 1169）、`:10180`（`_parse_episode_detail`，源行 1120）。原详情缓存 TTL 为 21600 秒；缓存命中时没有新平台请求。

这里的完整性需要比较平台声称的 `episode_cnt`、实际集列表数量与集序号。拿到一个非空 `video_list` 并不自动证明全剧完整。

## 6. 请求 C：每集 VID → 视频模型 → CDN 地址

```http
POST https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_model/v1/?<base_query>&_rticket=...
```

原 `get_video_urls` 每次最多放 5 个 `vid`，请求体：

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
    "1": ["<vid1>", "<vid2>"]
  }
}
```

先对这份精确 body 计算 `x-ss-stub` 并调用请求 S，再发送 POST。响应中 `data[vid].video_model` 是一个 **JSON 字符串**，还需 `json.loads` 一次，其 `video_list[]` 才包含轨道信息：

```text
response.data[vid].video_model (JSON string)
  → parsed.video_list[]
      ├─ main_url
      ├─ backup_url
      └─ video_meta.size / video_meta.definition / ...
```

原 `get_video_urls` 从轨道中选 `video_meta.size` 最大的一项，输出 `{url, backup, size, definition}`；它没有在此处对 URL 做 Base64 解码。`get_video_tracks` 则保留全部轨道，使用同一个平台接口。脚本输出可以同时保存所有轨道和选中的主/备用地址，而不只保留最大文件。

证据：`hongguo.dis.txt:17484`（`get_video_urls`，源行 1964）、`:17799`（`get_video_tracks`，源行 2003）。原视频模型缓存 TTL 为 18000 秒。未命中缓存且一次搜索即可选中时，N 集的正常冷请求量约为：`1 次搜索 + 1 次详情 + ceil(N/5) 次模型`，每次另有 1 次签名请求；重试、分页和辅助搜索另算。

至此已满足“输出下载地址”的协议终点。实际下载时才对 `main_url` 发 CDN GET，原基础下载函数开启 stream 并写 `.part` 后改名，相关证据为 `hongguo.dis.txt:21311`（`download_file`，源行 2491）。应区分“平台返回 URL”“CDN 当前允许读取”“文件可直接播放”这三个不同结果：媒体 URL 的有效期、返回类型或加密情况不能仅靠上述静态解析保证。

## 7. 无本地签名器的网页 SSR 备用链路

原程序还包含以下独立的公开网页加载器。统一加 query：

```text
__loader=<对应页面 loader 名称>
__ssrDirect=true
```

| 目的 | GET URL | `__loader` | 关键响应字段 |
|---|---|---|---|
| 搜索 | `https://hongguoduanju.com/search/<URL 编码关键词>` | `search_(keyword)/page` | `searchList[].video_data` |
| 剧详情/首集 | `https://hongguoduanju.com/player/<series_id>` | `player_(series_id)/page` | `seriesDetail`、`vid`、`video_player_info` |
| 指定可访问集 | `https://hongguoduanju.com/player/<series_id>/<vid>` | `player_(series_id)/(vid)/page` | `vid`、`video_player_info` |

加载器发 GET，关闭自动 redirect，要求状态码 200，再用 JSONDecoder 读取返回对象。证据：`offline_dl.dis.txt:9768`（`_hgdj_loader`，源行 1085）、`:10125`（`hgdj_search`，源行 1130）、`:9632`（`_hgdj_player_data`，源行 1056）。

网页剧详情的 `seriesDetail.vid_list` 可列出全部集 ID，但 `seriesDetail.accessible_episode_cnt` 才是网页公开可访问集数。对应媒体地址在 `video_player_info.main_url`，同对象还含 `poster_url/duration/width/height`。原 `hgdj_preview` 会根据 accessible 数量限制集号，超过返回 `locked`；它还验证返回 `vid` 与请求的目标相同，防止后端回退到首集而被误记为目标集。

证据：`offline_dl.dis.txt:10462`（`_hgdj_listing`）、`:11866`（`_hgdj_pv_episode`）、`:12068`（`hgdj_preview`）、`:12333`（读取 `accessible_episode_cnt`）、`:12456` 附近（超出 free 返回 locked）、`:12511` 附近（校验返回 vid）。

现有探测 [web-detail-probe.raw](evidence/web-detail-probe.raw) 返回《逆袭之实习教出金牌班，家长要换班主任》（`series_id=7689391720735181848`），`episode_cnt=111`、`vid_list` 长度 111、`accessible_episode_cnt=3`，首集 `video_player_info.main_url` 非空。这是**能列全 111 集，但不能据此声称得到 111 集地址**的直接例子。[web-search-probe.json](evidence/web-search-probe.json) 是对应的公开搜索探测证据。

所以网页模式应输出所有已知集的记录，对未公开可访问集标记 `locked` 或缺失原因；不得把首集 URL 复制到后续各集，也不得把只拿到前 3 集描述成“全剧地址完成”。APP 模式同样应逐集核对是否实际收到 URL，缺失时保留错误结果。

## 8. 已有运行验证与边界

在 Mac 上单独运行了提取出的 Java 签名服务 `com.hongguo.sign.FqTrace serve`，成功得到 8 个签名相关返回 header。第一次用安装包基础配置配合 Python `requests` 请求远端，HTTP 200 但响应为空；随后改用 `curl_cffi` 的 Chrome TLS 模拟，并用 `devices.json[0]` 的 query/UA 覆盖对应配置，关键词“逆袭”搜索返回 HTTP 200、285498 字节、业务 `code=0`。原始业务响应保存为 [signed-search-probe.json](evidence/signed-search-probe.json)。

由于传输实现和设备配置同时变化，不能据此单独断言是哪一个因素修复了空响应；两者都应保留为复现条件。运行提取出的独立 Jar 与运行原 Windows EXE 是不同测试范围。

随后使用本次重写的脚本完整执行搜索 → 选择第 1 部 → 详情 → 全剧视频模型。所选剧 ID 为 `7689391720735181848`，返回 111 集、111 个不同 vid、111 个不同主下载地址，共 555 条清晰度记录，错误数为 0。结果保存在 [完整 JSON](../outputs/逆袭111集.json) 和 [地址 TXT](../outputs/逆袭111集.txt)。该轮共 25 个平台请求（1 次搜索、1 次详情、23 次视频模型）和 25 个本地签名请求，全部 HTTP 200；[请求记录](../outputs/requests.jsonl) 包含具体请求体与响应。

对第 1、56、111 集各读取前 128 字节，均返回 HTTP 206、`video/mp4`、合法 MP4 `ftyp` 头。样本全部 555 条清晰度记录均为 `encrypt_info.encrypt=true`、`encryption_method="cenc-aes-ctr"`，所以这里验证的是地址覆盖率和 CDN 可读性，不是解密或完整播放能力。原程序还会执行按样本解密与重封装，见 [视频加密说明](VIDEO_ENCRYPTION.md)。验收记录：[live-verification.json](evidence/live-verification.json)。地址存在有效期，以模型 `url_expire` 为准。

REA 会话证据已导出到 [rea-evidence.json](evidence/rea-evidence.json)，保留 4 条完整记录。11 项离线测试覆盖精确签名参数、分页、缺集、批量模型、令牌脱敏、备用 URL 和异常增量保存。

## 9. 脚本输出应满足的验收条件

1. 搜索结果显示标题、`series_id`、集数，按序号选择，或直接输入 `series_id`。
2. 保存原始剧详情以及可读的剧元信息；逐集保存集号、`vid`、集名、时长、主 URL、备用 URL、清晰度及完整轨道。
3. 清晰区分 `episode_count`、实际目录数量、成功解析地址数量与失败/受限数量；缺失地址不得静默丢集。
4. APP 模式要求可用签名服务；网页模式无需本地签名器，但只能获取页面公开返回的地址。只输出 URL 不需要触发原软件的 `/dl/submit` 下载队列。
5. JSON 保存完整信息，TXT 保留每集的实际地址或缺失原因；带查询参数的 CDN URL 原样保留。

本报告已用上述样本跑通搜索到全剧 URL 的必要链路。其他接口是否可用仍需分别验证，不能由该样本外推。
