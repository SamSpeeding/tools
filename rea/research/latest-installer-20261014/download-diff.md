# 1.0.0.72 → 1.0.0.73 下载与播放调用链静态比较

日期：2026-10-14。范围：`offline_dl.pyc`、`downloader.pyc`、`server.pyc`。本文只依据安装包解出的 CPython 3.11 字节码；未导入、未执行目标代码，无平台请求。旧目录 `analysis/extracted/app` 及当前项目均未写入。

完整证据：[download-diff-evidence.json](download-diff-evidence.json)。JSON 内保留输入文件 SHA-256、每个代码对象的归一化摘要、两处改动的完整反汇编，以及下述调用边的指令窗口。此处的 DL-CALL 编号是本地静态分析证据编号，不是 REA 运行时证据编号。

## 结论

**新版在本报告涉及的模型入口中直接换用了单个 `video_model`，未修复或重试批量 `multi_video_model`。** `offline_dl._video_model` 从构造 `mixed_video_id_map` 改成 `video_id`，并配套修改响应解析。这能解释作者如何绕开批量失败，但静态包不能证明作者观察到的服务端根因，也不能证明新版 Windows 程序当前能正常运行。

下载调度、队列、并发上限、预取、异常退避在这三个模块没有语义变更。真正的离线下载调用 `hongguo.get_video_tracks`，另一些 API 使用 `hongguo.get_video_urls`；这两处需结合主调查的 `hongguo.pyc` 差异判断，不能仅根据 `offline_dl._video_model` 就宣称所有下载路径都已替换。

## 比较方法与覆盖

采用 Python 3.11 `marshal.loads(pyc_bytes[16:])` 读取代码对象，再用 `dis` 静态反汇编。没有 `exec`、目标模块 `import`、函数实例化或目标运行。逐层遍历所有嵌套代码对象，以嵌套路径及同名序号避免 lambda / comprehension 覆盖。

排除 `.pyc` 16 字节头、`co_filename`、`co_firstlineno`、`co_linetable` 的构建位置差异。比较其余参数计数、局部变量、栈大小、flags、字节码、常量、引用名、闭包及异常表；子代码单独比较。这样不会把新版构建目录缩短或插入 6 行引起的后续行号变化误报成功能修改。

| 模块 | 旧/新代码对象数 | 有直接语义差异的对象 |
|---|---:|---|
| `offline_dl.pyc` | 474 / 474 | `_video_model`、`_hgdj_pv_episode`，共 2 个 |
| `downloader.pyc` | 25 / 25 | 0 |
| `server.pyc` | 247 / 247 | 0 |

这里的语义相同表示上述静态结构一致；不等于同样代码面对不同外部配置、依赖或服务端时运行结果必然相同。

## 模型入口改动（确证）

`offline_dl._video_model`：旧源码位置 1516，新源码位置 1522。行号来自代码对象，不代表已恢复原始源码。

| 项 | 1.0.0.72 | 1.0.0.73 |
|---|---|---|
| HTTP 方法 | `POST` | `POST` |
| 路径 | `/novel/player/multi_video_model/v1/` | `/novel/player/video_model/v1/` |
| 目标字段 | `mixed_video_id_map: {"1": [str(vid)]}` | `video_id: str(vid)` |
| 读取模型 | `response.data[vid].video_model`，找不到该 key 时旧代码尝试取首个 value | `(response.get("data") or {}).get("video_model")` |
| 模型不存在 | 返回 `None` | 返回 `None` |
| 模型存在 | `json.loads(...)` | `json.loads(...)` |

`biz_param` 九个键及值完全一致：

```json
{
  "detail_page_version": 0,
  "device_level": 3,
  "disable_digg_stat": false,
  "disable_video_relate_book": false,
  "need_all_video_definition": true,
  "need_mp4_align": false,
  "use_os_player": false,
  "use_server_dns": false,
  "video_platform": 1024
}
```

精确指令证据：旧函数偏移 24 加载字符串 `1`，54/56 构造列表和 map，88 加载批量路径，150–302 执行按 VID 或首个 value 取值。新函数偏移 24–52 把 `str(vid)` 放进 `video_id`，82 加载单个路径，102–182 直接从 `data` 取 `video_model`。

新函数本身没有 `multi_video_model` 常量，没有请求失败后切接口的分支，也没有新增重试、设备更换、注册或刷新调用。它仍调用同一个 `H.api(...)`；该通用 HTTP 层在别处的变化需由 `hongguo.pyc` 比较核实。

## 实际调用关系与未变的调度（确证）

1. 原程序流媒体模型选择：`server._ensure_decrypted` → `server._vm_track` → `offline_dl._video_model` → `H.api`。其中 `_vm_track` 仍从 `video_list` 选择画质并返回 URL、`spade_a`、encrypt、definition、size。`offline_dl.main` 的 `quals` 分支也直接使用 `_video_model`。证据 DL-CALL-007 / 008，函数完整引用名见 JSON。
2. 原程序 GUI 离线下载：`server._dl_worker` → `offline_dl.download_series` → `EpisodePool`。预取线程 `EpisodePool._feed` 仍收集 VID 列表，调用 `H.get_video_tracks(vids)`。证据 DL-CALL-003 / 004 / 011。
3. 每集任务：`EpisodePool._work` → `_episode_task` → `dl_vid`。`_episode_task` 传 `retries=2`，同时传入预取的 tracks。`dl_vid` 首次尝试有 tracks 时复用；否则调用 `H.get_video_tracks([vid], force=(attempt > 0)).get(str(vid))`。捕获异常的分支仍等待 1.5 秒再重试。证据 DL-CALL-001 / 002。
4. 旧的 `downloader.DownloadManager` 批处理仍通过注入的 `get_video_urls` 取链接，单集 refetch 回调仍调用 `get_video_urls([vid], force=True)`。`server.api_play` 和 `api_video_url` 也仍调用 `H.get_video_urls`。证据 DL-CALL-009 / 010 / 012 / 013。

静态可确认的调度常量均未变化：

| 项 | 两版本相同值 | 说明 |
|---|---:|---|
| `SERIES_AT_ONCE` | 2 | 初始化默认值；运行时设置仍可调整 |
| `EPS_AT_ONCE` | 4 | 初始化默认值 |
| `MAX_TOTAL` / `MAX_CONN` | 16 | 默认连接上限 |
| `POOL_WORKERS` | 2 × 4 | 初始化推导值 |
| `TRACK_AHEAD` | 5 | 预取最多选取 5 项；不代表一次 HTTP 包含 5 个 VID |
| `RETRY_ROUNDS` | 2 | 全局重试轮次初始值 |
| `EpisodePool.GATHER_S` | 0.05 | 收集等待 |
| `EpisodePool.VERIFY_RETRY_S` | 10 | 分集列表校验重试等待 |
| `EpisodePool.VERIFY_TRIES` | 3 | 分集列表校验尝试次数 |

`EpisodePool._feed` 里的旧提示“预取直链失败，这 N 集将逐集取流”没有变化，不能拿这条日志字符串当成新版新增的单接口回退机制。预取失败后交给每集路径和服务不可用时自动暂停/继续均为旧有控制流。

## 与 App 批量故障无关的另一项变更（确证）

`offline_dl._hgdj_pv_episode` 是官网网页预览信息适配：

- 旧版读 `video_player_info.main_url`，要求 HTTPS；宽高缺失最终默认 720 × 1280，时长读 `duration`，海报读 `poster_url`。
- 新版读 `publicVideoSeo`，要求是 dict 且 `available is True`；取外层 `vid` 或 `itemId`，要求 VID 为 15–20 位十进制数字，且 `str(publicVideoSeo.itemId)` 与 VID 一致。
- 新版构造 `https://hongguoduanju.com/video/public/{vid}/360p.mp4`，宽高默认 640 × 360，时长读 `durationSeconds`，海报读 `posterUrl`。
- 仍由 `hgdj_preview` 使用，经 `server.dl_preview` 暴露。证据 DL-CALL-014 / 015。网页改动不属于用户限定的 App 平台下载链。

该函数只构造预览地址和元数据。不能从路径文字推断视频是否完整、实际时长或服务端是否当前可取；本轮没有请求这个网址。

## 对当前问题能回答什么

已回答：作者确实改动了模型接口选择；原始批量入口被单个入口替代；本范围没有签名算法修复、设备注册刷新、调度频率放宽、下载重试新增等变化。下载及播放上层仍保持相同的函数契约，因此改变可以局限于取模型的内部实现。

尚不能回答：批量接口服务器错误的根因；作者实际采用单接口的动机；新版 Windows 安装后当前可用性；`H.api` / `get_video_tracks` / `get_video_urls` 的全部差异（由主调查单独覆盖）；批量是否曾在作者网络恢复。

与我们先前单接口可用的观察一致，**可合理推断新版倾向于绕开批量问题，而不是让批量恢复**。这仍是依据静态差异与既有实测的推断，不冒充本轮运行结论。本轮不修改当前项目，也不继续此前平台实验。
