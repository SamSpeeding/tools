# 外部 HTTP API 与资源链路全集

本文件记录这份安装器的**调用端实际使用到的出站 HTTP 路径**，包括业务 API、公开网站 SSR、分享解析和动态资源模板。不是服务端完整 OpenAPI；响应字段是客户端消费到的字段，未被读取的远端字段仍可能存在。

静态核查覆盖 10 个业务 Python 字节码文件和打包下载器前端，共整理 **33 个出站路径/模板**。同路径的调用变体合并；没有新增调用许可、支付、更新、遥测或其他远端接口。机器清单：[remote-routes.json](evidence/remote-routes.json)。

已有搜索→详情→模型实测证据可以作为核心三接口的补充；其余项目以本文件的静态 evidence 为界，不声称已实测可用。所有许可证、anon key、设备 secret、session_id/token 的真实值均省略。

## 1. 红果 App API 公共协议

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

## 2. 分服务接口明细

### 红果 App API

#### `official.search` — 搜索与搜索翻页

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

#### `official.suggest` — 搜索建议与系列匹配

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

#### `official.plan` — 同 IP 系列/季/版本计划

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

#### `official.detail` — 整剧详情与分集目录

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

#### `official.models` — 每集全部播放/下载码率模型

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

#### `official.collection` — 当前身份的收藏/追剧列表

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

#### `official.rank` — 榜单、漫剧榜单与分页

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

#### `official.category` — 新剧、分类筛选面板、浏览流

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

### 公开网站备用与预览

#### `web.search` — 公开站搜索 SSR loader

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

#### `web.player` — 剧目录及默认预览页 SSR loader

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

#### `web.episode_player` — 指定剧集预览页 SSR loader

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

#### `web.detail` — 网页详情补充总集数

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

#### `web.rank.ai` — AI网页榜单

`GET https://hongguoduanju.com/rank/hot-ai-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

#### `web.rank.human` — 真人网页榜单

`GET https://hongguoduanju.com/rank/hot-real-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

#### `web.rank.comic` — 漫剧网页榜单

`GET https://hongguoduanju.com/rank/hot-comic-drama`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：未显式设置账号/token；_hgdj_session 网站 UA。

**响应**：HTML 中 series_id、标题和封面等；_hgdj_parse_rank 解析为剧列表。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**静态证据**：[hgdj_rank（原源码行971）](evidence/offline_dl.dis.txt)，证据文件第 9074 行；[_get（原源码行988）](evidence/offline_dl.dis.txt)，证据文件第 45306 行；[_hgdj_parse_rank（原源码行951）](evidence/offline_dl.dis.txt)，证据文件第 8867 行。

### 分享链接解析

#### `share.short` — 严格分享短链解析

`GET https://kylin.hainanyuyue.com | novelquickapp.com/s/{code}`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：无账号/token；User-Agent: Mozilla/5.0 (Linux; Android 12)。

**响应**：只读取状态码及 301/302/303/307/308 的 Location，解析 share 参数里的 series_id；不自动跟随此模式的跳转。

**用途和副作用**：读取数据；客户端会缓存或用于展示，没有观察到此请求主动修改用户收藏/点赞。服务端内部统计副作用未知。

**调用细节**：code 满足 [A-Za-z0-9_-]{4,32}。输入只接受这两个规范 host；Location 的品牌域规则另外涉及 hainanyuyue.com / applink.novelquickapp.com。该规则来自客户端静态代码，未抓取链接。

**静态证据**：[_share_link（原源码行571）](evidence/offline_dl.dis.txt)，证据文件第 6092 行；[_share_read（原源码行756）](evidence/offline_dl.dis.txt)，证据文件第 7571 行；[_share_sid_from_location（原源码行722）](evidence/offline_dl.dis.txt)，证据文件第 7230 行；[_share_series_id（原源码行778）](evidence/offline_dl.dis.txt)，证据文件第 7739 行。

#### `share.public` — 其他公开分享页/分享榜单解析

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

### 第三方 Catalog

#### `catalog.genres` — 目录分类标签

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

#### `catalog.explorer` — 全量目录分页/搜索/筛选

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

### 许可服务（Supabase RPC 形状）

#### `license.validate` — 验证许可

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

#### `license.activate` — 激活/重新绑定许可

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

#### `license.deactivate` — 停用本机许可

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

#### `license.download_check` — 免费额度/下载准入

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

#### `license.usage` — 额度与订阅状态

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

### 支付与账单

#### `pay.plans` — 购买套餐列表

`GET https://pay.hongguodownloader.com/plans`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：调用端未添加特殊 auth header；HTTPS-only session。打包版本固定 host，开发模式 HG_PAY_URL 可覆盖。

**响应**：返回 JSON；UI消费 plans[]，id/title/usd/interval/blurb/badge；失败回退缓存/空plans。

**用途和副作用**：读取套餐；缓存600秒。

**静态证据**：[dl_license_plans（原源码行3022）](evidence/server.dis.txt)，证据文件第 24002 行。

#### `pay.checkout` — 创建结账会话

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

#### `pay.key` — 查询购买结果并取许可密钥

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

#### `pay.portal` — 账单管理入口

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

### 版本更新

#### `update.release` — 最新版本元数据

`GET https://api.github.com/repos/M4St3r0/hongguo-downloader/releases/latest`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：Accept: application/vnd.github+json；User-Agent: HongguoDownloader；若HG_GITHUB_TOKEN非空，附 Authorization: Bearer <token>。

**响应**：tag_name（回退version）、html_url（回退url）、assets[].name/browser_download_url、body（回退notes）。选择首个.exe附件；版本比较后生成UI update结果。

**用途和副作用**：读取版本，缓存1800秒。

**静态证据**：[dl_update_check（原源码行3121）](evidence/server.dis.txt)，证据文件第 24822 行。

#### `update.installer` — 下载更新安装包

`GET https://github.com/M4St3r0/hongguo-downloader/releases/download/{tag}/{installer_name.exe}`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：HttpsOnlySession；此下载调用没有复用GitHub API的Bearer头。

**响应**：二进制安装文件，Content-Length可用于进度；客户端计算SHA-256并通过Windows Authenticode检查签名/发布者。

**用途和副作用**：写入本地 update/HongguoDownloader-Setup.exe；此请求本身不执行安装，/dl/update-run另行触发本地执行。本次未调用。

**调用细节**：URL来自release assets并通过固定github.com仓库前缀与.exe检查；服务端可能重定向到动态下载资源，不从字符串猜测新API。

**静态证据**：[dl_update_download（原源码行3161）](evidence/server.dis.txt)，证据文件第 25200 行。

### 可配置签名辅助服务

#### `signer.grab` — 刷新抓取到的App会话

`GET {SIGN_SERVER_base}/grab`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：可选 X-Sign-Token: <HG_SIGN_TOKEN>。

**响应**：url 与 headers，或 error。解析 URL query：仅更新config已有且不在DEVICE_KEYS集合内的字段；headers只提取cookie/x-tt-token/x-tt-store-region/x-tt-store-region-src。

**用途和副作用**：可能触发签名服务端抓取会话，随后修改本地config.json；仅第一个SIGN_SERVER，20秒刷新节流。本次未调用。

**调用细节**：base来自逗号分隔SIGN_SERVER环境变量，可能是127.0.0.1，也可能用户配置远端；不是固定外部域名。Jar是否实现/grab须看签名器文档。

**静态证据**：[refresh_session（原源码行437）](evidence/hongguo.dis.txt)，证据文件第 4955 行。

#### `signer.health` — 签名后端状态汇总

`GET {SIGN_SERVER_base}/`

**Query**：无额外业务查询字段。

**Body**：无。

**认证/头**：此stats()调用未附加X-Sign-Token；入口本地/stats先检查admin_token。

**响应**：ready、pid；请求失败汇总error。

**用途和副作用**：读取签名服务状态。

**调用细节**：host是否外部由SIGN_SERVER配置决定；/sign协议另见主API文档。

**静态证据**：[stats（原源码行737）](evidence/server.dis.txt)，证据文件第 7320 行。

### 媒体传输（非业务 JSON API）

#### `media.video` — 视频资源下载与Range续传

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

## 3. 榜单参数映射

| category | selected_items | recommend | hot | new |
|---|---|---|---|---|
| all | all | ranklist_hot_sc | ranklist_hot_play_sc | ranklist_new_rank_sc |
| human | human | human_hot_sc | human_hot_play | human_new_rank |
| comic | comic_series_rank | comic_series_hot_rank | comic_series_hot_play | comic_series_new_rank |
| ai | ai_playlet | ai_playlet_hot_sc | ai_playlet_hot_play | ai_playlet_new_rank |

最后三列是 `sub_selected_items`。映射在 `hongguo.py` 原源码 2352–2359 行；反汇编 [hongguo.dis.txt](evidence/hongguo.dis.txt) 第 2133 行附近。旧 `rank()` helper 固定漫剧榜。

## 4. 许可响应认证与支付边界

许可 RPC 统一 `POST /rest/v1/rpc/{fn}`，这是 Supabase/PostgREST 形状，但打包程序默认调用自有域 `api.hongguodownloader.com`，不直接由此证明后端部署细节。开发模式可从环境或 supabase.json 改 base。

每次请求生成 nonce。响应读取 `X-HG-Ts`、`X-HG-Sig`、`X-HG-Kid`，按本地公钥验证由 `ts + "." + nonce + "." + device + "."` 的 UTF-8 字节与原始 body 拼成的消息；打包版对无法验证的响应拒绝处理。这里只记录协议形状，不提供密钥/secret，也没有调用激活/解绑/额度计数。

许可安全协议证据：[_sig_message（原源码行177）](evidence/licensing.dis.txt)，证据文件第 1044 行；[_verify_msg（原源码行184）](evidence/licensing.dis.txt)，证据文件第 1097 行；[_rpc_raw（原源码行358）](evidence/licensing.dis.txt)，证据文件第 2438 行。

付款接口返回的URL由 `_safe_pay_url()` 检查：HTTPS且命中 checkout.stripe.com、billing.stripe.com、hongguodownloader.com（含程序允许的子域规则），随后 `webbrowser.open()`。安装包内没有据此观察到对 Stripe REST API 的直接调用；浏览器进入页面后的网络协议不在此安装包静态证据范围。

## 5. 不应误算为远端业务 API 的项目

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

## 6. 覆盖范围与剩余未知

已静态扫描上述10个pyc的递归code object URL/path常量，并沿请求发送函数核对每个固定路径及动态URL读取调用；增加检查打包HTML/JS直接 fetch，因此包含不经Python后端的Catalog请求。机器清单带每个被审阅工件SHA-256与函数/原源码行/反汇编行。

此处完整指**该构建调用端可见路由范围**。远端服务可能还有本程序没有调用的endpoint；服务端严格必填字段、全部错误码、限流规则与隐藏副作用无法仅凭客户端证明。动态配置SIGN_SERVER/开发模式host/分享URL/CDN URL只能记录模板。

没有执行原pyc模块，没有新增访问许可/支付/更新/报告接口，也没有把静态函数存在性描述成运行时调用事实。核心导出脚本的实测结果见此前生成的请求轨迹和 live-verification.json。
