# 首版验证记录

首轮日期：2026-10-13；后续回归更新至 2026-10-14。主机：Apple Silicon Mac，macOS 26.7.1。

## 当前结论

2026-10-14 后续集成：使用原固定设备、原请求参数和 JAR 其余签名，由独立 `hongguo_hm` 模块替换 Helios / Medusa 后，批量视频模型重新通过真实请求检查。桌面与 CLI 均已接入；详情见 [本地签名说明](本地签名.md) 和 [集成证据](evidence/hm-integration-20261014/README.md)。下方为前一阶段单接口回退的历史结果，不能解释为当前批量接口仍不可用。

## 前一阶段：单接口回退

**新应用的真实平台视频下载、解密及整段音视频解码已通过。** 原包使用的批量接口 `/novel/player/multi_video_model/v1/` 在当前条件下返回 `Code:110001`；使用相同平台 host、`aid=8662`、原设备第 0 组、签名器及业务参数，改用单视频接口 `/novel/player/video_model/v1/` 和 `video_id` 请求体后取得 5 档视频地址。按用户后续要求，当前版本优先批量、失败后自动回退单视频，并显示实际来源。

原字节码的在线受控回放也复现了旧批量接口失败，因此不是只在新 UI 或改写客户端中失败。但没有运行完整 Windows EXE，不能推广为所有版本、设备或网络下原程序都不可用，也不能据此断言平台已停用该接口。新注册设备仍无法修复旧批量请求；原有设备成功完成单视频请求，说明本次修复无需更换设备配置。原 `analysis/`、原 CLI 和两份配置未修改。

## 已通过

| 范围 | 验证结果 |
| --- | --- |
| 构建 | TypeScript 检查、Vite 构建、Rust release、Tauri `.app` 打包通过 |
| Mac 启动 | 在 Finder 双击最终 `release/HongguoDesktop.app`，真实列表、分类筛选和海报显示 |
| 榜单 | 全部／真人／漫剧／AI × 推荐／热播／新剧，共 12 组合均返回结果；默认榜单首／次页通过 |
| 分类与最新上架 | 三种体裁的动态面板、非空题材筛选和首／次页通过 |
| 原生列表交互 | 最新上架点击“加载更多”从 16 部追加到 32 部；打开第二页剧目的 79 集详情，返回后仍保留 32 部列表 |
| 搜索 | “重生”首／次页通过；原生界面搜索“坠崖捡个参娃娃”显示结果 |
| 详情 | 取得“坠崖捡个参娃娃”74 集，完整性检查通过；原生详情与单集按钮可见 |
| 队列 | 自动测试验证串行、重复点击去重、取消等待项／进行项、重试、重启不自动下载 |
| 媒体流水线 | 独立生成本地 HEVC/AAC 加密样本，经本机 HTTP 下载、大小／哈希检查、解密、封装、全量解码；成品音视频流哈希与原片相同 |
| 真实平台下载 | “坠崖捡个参娃娃”第 2 集，1080×1920、HEVC/AAC、62.415 秒、4,480,838 字节；完整下载、解密、封装及全量 FFmpeg 解码通过，成品 SHA-256 与历史 CLI 成品一致 |
| 最终 Mac 包下载 | 最终 `release/HongguoDesktop.app` 中重试测试分集，界面显示“已完成”和“打开文件夹”，持久任务状态为 completed，保存到默认 `~/Downloads/HongguoDesktop/` |
| 流式解密后端 | 真实第 2 集只读取 262,144 / 4,507,067 字节即准备完成；HEAD、首段和非对齐中间 Range 正确，整条明文流经 FFmpeg 全量解码通过 |
| 最终 Mac 包播放 | 第 2 集 1080p 显示视频并推进时间；暂停、跳转至 31 秒后继续播放；切第 3 集和 720p 成功；关闭后各旧播放 URL 均返回 404 |
| 源码依赖 | 媒体测试使用只含 `.py` 的依赖目录；最终应用的解密目录也仅含四个 `.py` |
| 文件保护 | 成品校验后跳过、不再请求 API；修改过的同名文件拒绝覆盖 |
| 媒体进程取消 | 中断正在运行的媒体子进程，不遗留长时间运行进程 |
| 自动测试 | 18 项 Python 测试通过；覆盖模型回退、队列、完整下载与流式解密、Range／索引检查、播放关闭和成品保护等 |
| 界面回归 | 8 项前端测试通过：进度原位更新、来源标识、浏览不调用模型、播放按需启动、视频节点稳定、过期响应丢弃、跳播不重新显示遮罩及缓冲提示延迟／取消 |
| 原生退出 | 修复 macOS 原生 Quit 绕过普通窗口事件的问题；⌘Q、窗口关闭均实测显示任务确认；继续下载可留在应用，停止并退出后 Python／Java 进程退出 |

## 接口修复与当前成功对照

### 原字节码实际在线回放

`scripts/probe_original_models.py` 从原 `hongguo.pyc`、`devicepool.pyc`、`safeguards.pyc` 取出经过检查的原始函数代码，执行 `get_video_tracks → api → _api_once → build_url/_req_headers → sign → http_request`，使用原设备选择与响应检查逻辑。没有执行原模块顶层、Windows GUI、授权、支付或升级流程。缓存关闭，后台检查／统计等外围行为受控替换；网络限定本机签名器和两个官方内容 endpoint。所有替身、代码哈希和实际调用次数均记录在证据中。

设备第 0 组：详情返回 74 集，模型返回 HTTP 200 / `Code:110001`，原 `get_video_tracks()` 最终返回空字典。第 34 组模型也相同。原响应检查未抛异常，既未刷新会话也未轮换设备，反而调用了 `source_good`。这确认这份安装包的原始下载请求逻辑在本次配置、Mac 运行时和网络条件下失败；不等同于运行完整 Windows 程序。

### 注册实验与接口对照

借鉴用户提供的 PHP 注册入口，执行少量候选请求，TLS 证书校验保持开启，所有返回仅保存于新项目诊断目录，没有写入运行配置：

- `com.dragon.read` 最小字段候选：返回非零 `device_id` 与 `install_id`。
- 仅换成当前 package 的最小候选：返回两个 ID 均为 0。
- 当前 package 加 `aid=8662`、应用版本、硬件／系统等元数据候选：返回非零成对 ID 和 device_token。这是可用实验样本，不代表已复原官方完整注册、续期或激活协议。

保持同一分集、App 身份、签名器和业务参数，取得如下在线对照：

| 设备 | 批量接口 + mixed_video_id_map | 单视频接口 + video_id |
| --- | --- | --- |
| 原 `devices.json[0]` | `110001`，无地址 | 成功，5 档视频均有地址 |
| 新注册成对 ID | `110001`，无地址 | 成功，5 档视频均有地址 |

另将旧批量路径仅换成 `video_id` 仍失败；继续将路径改为单视频接口后成功。单视频响应模型位于 `data.video_model`，而非旧的 `data[vid].video_model`。该相邻对照把修复集中到接口和请求／响应结构差异；不能解释平台内部为何拒绝旧请求。

首次修复时新应用的 `models()` 逐集调用单视频接口，并保持按请求分集 ID 索引的内部返回结构。后续改为下面记录的批量优先／单视频回退策略；一集失败不挪用另一集模型。未增加自动注册、机械轮换或不可用的 `/grab` 刷新。原始研究及 CLI 保留原样。

### 修复后完整验证

复现命令：

```sh
.runtime/python/bin/python3.11 -B scripts/repro_model.py
```

首次单视频修复的输出为 `passed: true`，2.44 秒，`model_count: 1`，`errors: []`。`scripts/smoke_worker.py` 随后完整通过：搜索、12 种榜单、分类／最新上架及分页、详情、下载任务去重、下载期间浏览和真实单集媒体校验。当前回退策略的快速检查结果见下一节及最新 `model-repro.json`。

成功样本：`docs/evidence/downloads/坠崖捡个参娃娃_7689863296106646590/第002集_1080p.mp4`，SHA-256 为 `ffbfcfb34273e650cc4c02a2221959a69a33b8cc46685a62dec352edafdad794`。修复前失败记录独立保存在 `model-repro-before-fix.json`、`worker-smoke-before-fix.json`。

### Mac 成品保存修正

打包应用中的真实重试完成解密和 FFmpeg 校验后，曾停在成品发布阶段。macOS `sample` 显示 Python 下载线程持续阻塞于 `os_link → link(2)`，当时无 FFmpeg 子进程；界面仍显示最后一个“校验音视频”状态。尚未判定内核或文件系统为何挂起硬链接操作，未改动任何系统安全设置。

Mac 改用 `renamex_np(..., RENAME_EXCL)`，把同目录内已完成验证的临时成品原子移动到最终路径，目标存在时失败，保留原有不覆盖保证。函数及标志来自本机 SDK `sys/stdio.h`；新增实文件测试覆盖首次发布成功和已有目标拒绝覆盖。Windows 分支使用目标存在即失败的 `os.rename`，仍未做 Windows 运行验收。

重新打包后，在最终 `.app` 中点击同一测试分集的“重试”，原生界面及持久任务状态均显示完成，保存路径为 `/Users/tt/Downloads/HongguoDesktop/坠崖捡个参娃娃_7689863296106646590/第002集_1080p.mp4`。应用完成状态由全量校验和最终保存成功后设置。终端对 Downloads 的独立读取另有停滞，已取消，因此上文精确哈希和媒体数值引用集成测试成品，不冒充对 Downloads 成品的第二次独立测量。

## 批量优先、单视频回退与来源标识

后续按用户要求，每个下载任务首先调用 `/novel/player/multi_video_model/v1/`，`mixed_video_id_map` 仅包含当前任务的分集。成功且有可用模型时不再调用单视频接口；业务错误、传输错误、缺少模型、无法解析模型或没有可用地址时，调用 `/novel/player/video_model/v1/`。签名器本身不可用时直接失败，避免对同一不可用签名器重复调用。不同清晰度选择和 CDN 传输仍按原下载逻辑处理。

任务保存 `model_api`、`model_api_state`、`model_fallback` 和 `model_fallback_reason`。状态旁原位显示当前请求或最终选用的接口；回退成功显示 `video_model · 已回退`，悬停可查看批量失败原因；完成后仍保留，成品校验 JSON 也记录来源。手动重试清空上次来源再重新请求；已有校验通过的成品标为“本地已校验 · 无接口请求”。旧任务没有记录时明确标为未记录，不推测历史来源。

调用时机：桌面 UI 的列表、搜索、筛选、详情路径只请求对应内容接口。`enqueue` 只入队，轮到任务执行时才经 `jobs.download()` 请求模型；手动重试同样入队。后续新增播放器在用户明确播放、重试、切集或切换清晰度时也请求模型；进度跳转复用本次模型。没有模型预取、定时刷新或重启自动下载。独立诊断脚本 `repro_model.py` 会显式请求模型，不属于应用的浏览行为。

该轮在线快速检查 1.76 秒通过：同一 host 的批量接口返回 `110001`，单视频接口成功，`model_api=video_model`、`model_fallback=true`、最终 `errors=[]`，两次尝试均记录在 `model-repro.json`。该轮所有请求固定使用 `api5-normal-sinfonlinec.fqnovel.com`，当时未覆盖另一官方 baseUrl；后续独立对照结果见下一节。

最终 Mac 包实际下载“坠崖捡个参娃娃”第 3 集 1080p：界面依次观察到 `multi_video_model · 请求中`、`video_model · 已回退`，完成后仍显示回退接口。持久任务状态为 completed，来源为 video_model，回退原因记录为批量接口 `110001`。新标识排版已截图检查，任务面板节点保留且状态原位更新；旧历史记录显示未记录。

## 原程序两个 baseUrl 的在线对照

2026-10-13 18:25（Asia/Shanghai），按用户要求执行 `scripts/probe_model_hosts.py`。原包备用常量 `API_HOST_B` 是 `api5-normal-sinfonlineb.fqnovel.com`，证据为冻结的 `analysis/evidence/hongguo.dis.txt:1366`；原 `api()` 在 `_conn_failure(e)` 判定连接失败后切换备用域名（同文件 6244–6267 行），不是遇到任意业务错误都会切换。此前受控原字节码实验将备用域名限制为主域名，因此不作为跨域名测试证据。

本次保持原设备第 0 组、`aid=8662`、同一签名器和 HTTP 客户端、同一分集 `7689903116275174462`，每个完整 URL 重新签名。同接口在两域名上的请求体 SHA-256 相同；时间戳和签名按请求生成。直接调用每个接口，绕过应用的自动单视频回退，顺序为 c 批量 → b 批量 → c 单视频 → b 单视频 → c 批量复测。

| baseUrl | `multi_video_model` | `video_model` |
| --- | --- | --- |
| `https://api5-normal-sinfonlinec.fqnovel.com` | HTTP 200，`Code=110001`，未知异常；复测一致 | HTTP 200，`code=0`，5 档地址 |
| `https://api5-normal-sinfonlineb.fqnovel.com` | HTTP 200，`Code=110001`，未知异常 | HTTP 200，`code=0`，5 档地址 |

两边单视频模型均可解析出 360p、480p、540p、720p、1080p 的 HTTP(S) 地址。结论：在此次设备、分集和请求条件下，切换原备用域名没有修复批量接口；备用域名本身能正常返回单视频模型。本次没有通过备用域名返回的地址下载或解码媒体，不扩大为备用域名完整下载验收，也未查明服务端业务错误的根因。

只新增诊断脚本、结果和本记录；应用 host、设备配置、签名器及下载回退策略均未改动。配置和设备文件前后哈希一致，见 [完整对照记录](evidence/model-host-comparison.json)。冻结的 `analysis/` 保持不变。

## 批量接口类型与 device_id 对照

2026-10-13 按用户提出的两个假设独立测试，均直接请求批量 endpoint，不经过单视频自动回退：

- 类型键：保持原设备和签名链路，c、b 两个域名分别按 `1 → 1004 → 1 → 1004` 请求同一 vid，8 次均返回 `110001`。见 `model-type-comparison.json`。
- 只换 `device_id`：执行 `scripts/probe_batch_device_id.py`，顺序为原 ID → 新 B → B 重试 → 原 ID → 新 C → C 重试。6 次均为 HTTP 200、`Code=110001`，没有可用模型。固定 c 域名、7.2.9.32、类型键 1、原 iid/cdid/UA/其余字段及 JAR/SO 签名链路；每次按实际请求重新签名。

B、C 是在内存生成的同位数随机 ID，未做平台注册，也不写入生产配置；不能把它们称为已注册的新设备。配置前后 SHA-256 一致。该结果表明“只改 device_id”不足以修复当前应用的批量请求，不证明设备状态完全无关，也不能据此确定 IP 或服务端内部规则。独立研究脚本中的换 ID 成功现象属于另一套版本／请求／签名组合，不能直接推广到本应用。详见 [六次完整记录](evidence/batch-device-id-comparison.json)。

## 分集流式播放

用户追加播放功能后，在详情的每集旁加入独立播放按钮。播放器支持原生暂停／进度控制、上一集／下一集、选集、画质切换和手动重试；切换从头开始，不自动连播。播放走现有 App 模型和 JAR/SO 签名器，未移植研究脚本的签名、随机设备 ID 或网页入口。`analysis/` 和原 CLI 未改。

worker 新增 `playback_open` / `playback_close`，模型准备在独立线程执行；媒体服务只监听 127.0.0.1 随机端口，用随机路径标识当前播放会话。按播放器 Range 请求读取 CDN 的 256 KiB 分段，内存密文缓存最多 8 段；严格检查 206、Content-Range 和长度。解析 MP4 样本索引和逐样本 IV，复用现有 spade 解包和密钥快筛，用 AES-CTR 解密请求范围并改写加密标记，保留文件偏移。索引在文件尾时按顶层 box 大小跳过 mdat，不先下载整集。此版支持当前已测非分片 CENC MP4；其他加密／索引布局会明确报错。

真实集成验证 `scripts/smoke_playback.py`：原设备第 0 组，坠崖捡个参娃娃第 2 集 1080p，批量 `110001` 后单视频成功。2.846 秒进入 ready，此时仅收到 262,144 字节，总大小 4,507,067 字节。HEAD 为 200，首段和非对齐中间 Range 为 206，范围内容与整条输出对应位置一致；整条明文流通过 FFmpeg 严格全量解码。SHA-256 为 `d41be261a5b7c3e7c2c06c4046e354c0bbc8a7f7b1ead1348f2af4d617b5bc96`；流保留原 box 大小，与下载后重新封装的文件哈希不同。没有创建下载任务。测试保存的整条流仅是诊断样本，正常播放不落盘。

最终 `release/HongguoDesktop.app` 在本机原生 WebView 实测：第 2 集画面可见且时间从 4 秒推进到 20 秒；暂停后操作进度条跳到 31 秒，继续播放成功。切第 3 集 1080p 后再次出画面并推进时间，再切 720p 成功。状态均显示 `video_model · 已回退`。关闭后返回详情，下载任务仍为 0，三个已观察播放 URL 的 HEAD 均为 404。截图与辅助功能树未见控件遮挡或文字裁切。

18 项 Python 测试和 6 项 UI 测试通过，最终小幅循环优化后的 4 项播放专项测试再次通过。独立 FFmpeg 生成的加密样本覆盖文件尾索引和任意非对齐范围，解密后的音视频哈希与原片一致；自动测试同时验证拖动不重新请求模型、关闭准备中的旧会话不能发布 ready、任务进度不替换 video 节点。TypeScript、Vite、Rust release 和 Tauri 打包通过，最终包约 178.58 MiB。证据见 `playback-smoke.json`、`native-ui-check.json`、`unit-tests.log` 和 `progress-ui-tests.log`。

## 播放进度跳转闪烁修复（2026-10-14）

用户报告预览播放时点击进度条会闪。原 `seeking` / `waiting` 事件立即给 `.player-stage` 加上 `loading`，显示覆盖整个视频的半透明启动遮罩；`seeked` / `playing` 又移除遮罩。即便数据已经缓存，短暂事件序列也会让画面明暗交替。旧测试只覆盖任务更新不替换 video，没有覆盖播放器自身的跳转事件。

新增测试直接运行生产入口的事件处理器，先触发首帧和播放，再触发一次 seeking；修复前稳定失败于“seek must not cover the visible frame”。修复后，整块遮罩只用于首次出画面；跳转和等待保持原 video、src 与画面，不再重新加遮罩。缓冲持续 300 毫秒才在底部显示文字，恢复、失败、切集和关闭会取消待显示提示；相同状态文字不重复写入 DOM。未改动接口、签名、设备或后端解密逻辑。

8 项 UI 回归测试通过，覆盖连续跳转、等待／恢复、暂停跳转、失败和关闭的提示取消，以及原有下载进度和播放生命周期。TypeScript、Vite、Rust release 和 Mac 打包通过。

修复后的最终 Mac 包实测同一剧第 2 集 1080p：暂停于约 42 秒，点击原生进度条后跳到 31 秒，画面可见，未重新出现“正在准备这个故事”；恢复播放后时间推进到 48 秒。视频容器、播放 URL 与外部面板保持不变。原生截图检查覆盖跳转前后，毫秒级遮罩状态及连续事件序列由上述回归测试精确验证。应用已更新并留在详情页。

## 下载进度闪烁修复

用户报告每次下载进度变化，任务界面都会闪烁。前端原 `acceptJob()` 对每个进度事件调用 `renderTasks()` 和 `renderEpisodes()`；前者整块替换抽屉 `innerHTML`，重新播放 `.drawer` 的 `slide-in` 入场动画，后者重新创建分集加载图标。重建进度条还打断了宽度过渡，并使取消按钮丢失键盘焦点。

先用 `node --test tests/test_progress_ui.mjs` 执行真实 `src/main.ts` 的入口和事件监听，只替换原生 IPC 与 CSS 导入。修复前两个测试均失败，最小一次进度事件即可重建抽屉。修复后，抽屉只在打开时创建；任务卡片按 ID 复用，百分比和进度条原位更新；分集仅在状态变化时更新对应按钮，过期事件直接忽略。

同一测试修复后全部通过，覆盖连续百分比变化、节点与加载动画连续性、焦点／滚动、解密／校验／完成、任务加入及操作有效性。`npm run build` 和最终 Mac 打包通过。`jsdom` 仅为开发测试依赖，不进入应用运行包。

最终 Mac 包中重试已有失败任务“我救的山鸡，竟是三足金乌”第 1 集：从获取视频、解密到已完成，抽屉、任务卡片与按钮的原生辅助功能节点保持稳定，只更新状态文字和动作；最终成品保存成功。百分比更新过快未逐次截取，连续百分比稳定性由上述事件回放测试验证。应用已打开并留在完成状态。

## 修复前诊断记录

以下保留定位过程；其中“模型请求”均指旧批量接口。

已比较：

- 新项目环境与完整旧 CLI 环境（旧 `.venv`、旧模块、旧 vendor 和配置）；相同错误。
- 曾下载成功的分集、另一部热榜剧及最新 AI 剧；相同错误。
- 既有默认设备、另一条既有设备和原配置；相同错误。
- curl_cffi Chrome、普通 requests，以及 HTTP/1.1、HTTP/2；相同错误。
- 请求体 MD5 与实际 `x-ss-stub` 相符；常用四个签名头存在。**字段存在不等于平台认可其动态状态。**
- 使用完整与最小业务请求体；相同错误。
- 同时搜索、榜单、分类、详情成功；目前错误集中出现在视频模型请求。

没有保存下来的历史成功完整网络请求可逐字重放，只有接口文档、代码、历史成品与验证摘要。用户已确认没有可运行的原版下载器。此阶段尚无成功请求，不能判定平台内部原因；随后取得的单视频接口成功对照与原字节码在线回放见上文。

### 设备配置专项核对

用户提出设备配置可能失效后，新增 `scripts/probe_device_config.py`，保持同一签名器、接口、分集、请求体和传输实现，按 `devices.json[0] → [34] → [68] → [0]` 顺序对照。每次详情均取得 74 集且目标 vid 匹配，视频模型均返回 `110001`。请求 URL 的 `device_id/iid/cdid` 与所选记录一致，UA 也一致。

新应用固定选第 0 组。设备文件有 69 组不同身份，均只覆盖 `device_id/iid/cdid`，UA 均与基础配置相同；两份配置文件与原 CLI 完全一致。基础请求头没有 Cookie 或 `x-tt-token`，因此本次没有发现删除现有会话凭据或复制时混用 ID 的问题。

仅凭此阶段结果，不能排除新旧客户端共同的设备／会话问题，也不能证明全部设备无效或平台故障。后续单视频接口已用原第 0 组成功，补齐了当时缺失的成功对照。未更改运行配置，也未自动轮换全部设备。

### 原下载器设备生命周期与 PHP 参考复核

2026-10-13 补查原始 `devicepool.pyc`、`hongguo.pyc`、`safeguards.pyc`，原 Java 签名器及启动器证据，并只读检查用户指定的 `/Users/tt/video-downloader/video-api/`。此静态／离线审计阶段没有平台注册请求。后续独立注册实验见上文；参考 PHP 未执行，当前配置和原 `analysis/` 保持不变。

**结论：当前实现省略了原程序的设备池轮换和可选会话刷新分支，但未发现原下载器自身调用设备注册接口。不能把这些实现差异直接归因为本次 `110001`。**

| 问题 | 已核实行为 | 证据 |
| --- | --- | --- |
| 原设备从哪里来 | `DEVICE_POOL` 可指定 JSON 路径；默认读取随包 `devices.json`。当前 69 组与提取出的原文件逐字节一致。作者如何获得这批预置 ID，包内没有给出来源记录。 | `analysis/evidence/devicepool.dis.txt:529`；`device-reference-scan.json` |
| 原程序会注册吗 | 文件缺失／读取失败且 `DEVICE_POOL_SIZE > 0` 时，`gen_device()` 本地生成随机数字 ID、UUID 和机型／UA，并尝试写入文件；这是本地生成，不是平台注册成功。默认生成数量为 0。该模块完整函数中无网络调用，导入仅 json/os/random/threading/uuid。 | `devicepool.dis.txt:288`、`:529`；新 `device-lifecycle-bytecode.txt` |
| 如何选和换设备 | 默认文件采用会话固定模式，启动随机选一组；显式 `DEVICE_POOL` 路径使用线程内固定设备。`rotate()` 从已有列表继续取一组，不重新注册、不刷新服务端凭据。 | `devicepool.dis.txt:774`、`:942`、`:1005` |
| 何时刷新／轮换 | `api()` 捕获 `AuthExpiredError` 时调用 `refresh_session()`；捕获 `RiskControlError` 时轮换并退避；部分传输／解析错误也轮换重试。当前应用固定第 0 组，未移植这些分支。 | `hongguo.dis.txt:5954`；`backend/worker.py:39` |
| 刷新数据来源 | `refresh_session()` 请求第一个 `SIGN_SERVER` 的 `/grab`，最多每 20 秒一次；消费返回的 URL 和 headers 并写入 `config.json`。它消费抓取结果，不在该函数内实现手机抓取或平台注册。 | `hongguo.dis.txt:4955` |
| 本包刷新入口能用吗 | 启动器把 `SIGN_SERVER` 指向本地 FqTrace；该 Java 实现仅注册 `/sign`。同份本地签名器的 `/grab` 实测 HTTP 404。另行部署且实现 `/grab` 的服务是否可用，未验证。 | `app.dis.txt:12381`；`FqTrace.javap.txt:837`；`grab-probe.json` |

**旧文档勘误：** `analysis/REMOTE_API.md:850` 的“仅更新 config 已有且不在 DEVICE_KEYS 集合内的字段”记录反了。原字节码实际构造 `set(base_query.keys()) | {'device_id','iid','cdid','klink_egdi','channel','update_version_code'}`，遍历这个集合，把抓取 URL 中存在且非空的值写回基础 query；所以包括设备身份。请求头只更新 Cookie、x-tt-token、地区及地区来源，不更新 UA。已用原 `refresh_session` 函数和模拟 I/O 验证：设备 ID、iid、cdid、版本、channel、klink_egdi 均能更新，未知 query 不写入，第二次调用被 20 秒限制挡住。为遵守冻结要求，更正在此记录，原分析文件未改。

还有一个作用边界：启用设备池时，`build_url()` 又用池中设备覆盖基础 query；`_req_headers()` 还会删除 Cookie/x-tt-token。因此“刷新 config”不等于默认设备池已换成新身份／会话。证据为 `hongguo.dis.txt:5449`、`:5570`。

**当前错误是否触发原刷新逻辑：** 对原 `safeguards.check_response()` 做离线受控回放，当前大写 `Code:110001` / `BaseResp.StatusCode:110001` 仅返回而不抛异常；小写 `code:110001` 会抛 `RiskControlError`，`code:401` 配合 `session expired` 会抛 `AuthExpiredError`。原因是原函数只读取顶层小写 `code`，没有读取大写 Code 或 BaseResp.StatusCode。因此当前响应不会通过这个检查函数触发刷新／轮换；这不代表我们已在 Windows 上运行原程序或覆盖其所有外层重试行为。

**PHP 参考能提供什么：**

- `VideoEndpoint.php:102` 和 `Video3Endpoint.php:102` 从 `key.json` 中 `key` 的 `@` 后读取 device_id；只有文件不存在／格式不符才注册。`update_time` 只写入，从未用于过期检查，视频接口失败也不触发重新注册。
- 两个 `registerDevice()` 在 `:134` POST `https://i.snssdk.com/service/2/device_register/`，只提交 `package=com.dragon.read`、随机 openudid 和随机机型。仅保存响应 device_id，未保存 iid/install_id/cdid、机型或会话。后续有限候选请求结果见上文，不代表持续成功率。
- 它的视频调用使用 aid=6589/wkbrowser 或 aid=357/news_article；当前链路是 aid=8662/novelread。请求 host/path、body（video_id 对比 mixed_video_id_map）、部分 video_platform、签名也不同。即使借用注册得到的一个 ID，也不能证明与当前应用身份和其余设备字段匹配。
- 可参考“设备档案缺失时获取并持久化”的设计和注册 URL。不能直接照搬为修复，也不应把当前参数整套替换后宣称已经定位设备问题。参考代码关闭证书校验的设置不应移植；现有客户端继续校验证书。网页 `book` 分支不符合本项目约定范围。

与 `aid=8662` 对应的完整设备／会话生命周期仍未复原，候选注册只证明服务端能返回一组成对 ID。后续对照已证明此次修复无需换设备；没有为此将候选注册接入生产逻辑。原包缺少有效 `/grab` 刷新源，机械添加该调用或随机 ID 无法形成可靠续期机制。

离线审计命令：`.runtime/python/bin/python3.11 -B scripts/audit_device_lifecycle.py`。REA 受控回放 Evidence：`ev_f7b742774229b425640b8c1653d6f168dbf352670a0fb01923ce63199a9fab51`，退出码 0。仅执行经过检查的两个函数，网络及配置写入均被模拟／限制在临时目录；不是平台在线成功请求。REA 的进程捕获不提供网络系统调用审计，具体替身与边界见脚本。完整证据已另存新项目目录。

## 未验证范围

- 完整 Windows 原程序、全部设备与剧集、平台服务端内部失败原因。
- 另一台干净 Mac、Intel Mac、Windows、独立 Java/FFmpeg 打包、开发者签名和公证不属于本次已验证范围。

## 证据文件

- [发现接口首／次页](evidence/app-discovery-probe.json)
- [常驻 worker 集成检查](evidence/worker-smoke.json)
- [单元与加密媒体测试](evidence/unit-tests.log)
- [构建日志](evidence/build.log)
- [模型接口快速复现](evidence/model-repro.json)
- [原程序主／备用域名模型接口对照](evidence/model-host-comparison.json)
- [批量请求类型键对照](evidence/model-type-comparison.json)
- [仅更换 device_id 的六次对照](evidence/batch-device-id-comparison.json)
- [真实平台流式播放集成检查](evidence/playback-smoke.json)
- [批量优先功能实现前的测试](evidence/model-fallback-before.log)
- [修复前模型失败](evidence/model-repro-before-fix.json)
- [修复前集成检查失败](evidence/worker-smoke-before-fix.json)
- [原字节码在线受控回放](evidence/original-bytecode-model.json)
- [设备注册候选实验概要](evidence/registration-probe.json)
- [新旧设备与旧批量接口对照](evidence/registered-model-probe.json)
- [原设备与接口契约对照](evidence/model-contract-probe-device-0.json)
- [新注册设备与接口契约对照](evidence/model-contract-probe.json)
- [原生应用验证](evidence/native-ui-check.json)
- [应用包源码和原配置一致性](evidence/bundle-source-check.json)
- [Mac 保存阻塞线程采样](evidence/native-save-link-sample.txt)
- [进度闪烁修复前复现](evidence/progress-ui-before-fix.log)
- [进度界面回归测试](evidence/progress-ui-tests.log)
- [播放跳转遮罩问题修复前复现](evidence/playback-seek-before-fix.log)
- [跳转闪烁修复后的八项 UI 测试](evidence/playback-seek-ui-tests.log)
- [跳转闪烁修复版构建日志](evidence/playback-seek-build.log)
- [完整旧环境复现](evidence/old-environment-model.json)
- [HTTP 协议、实际请求体与响应头对照](evidence/request-comparison.json)
- [多组诊断概要](evidence/video-model-diagnostic.json)
- [设备配置受控对照](evidence/device-config-check.json)
- [原设备／刷新函数离线审计](evidence/device-lifecycle-audit.json)
- [原字节码的本次反汇编](evidence/device-lifecycle-bytecode.txt)
- [REA 受控回放证据包](evidence/device-lifecycle-rea.json)
- [本地签名器 grab 实测](evidence/grab-probe.json)
- [13 个打包 Python 模块的设备引用扫描](evidence/device-reference-scan.json)
