# HongguoDesktop

Tauri 2 + 原生 TypeScript 网页 + Python 的 Mac 桌面预览版。仅使用平台 App 内容接口。

**当前状态：找剧、详情、下载及分集流式播放已通过本机 Mac 验证。** 播放和下载均优先请求原批量视频模型接口；请求失败、模型不完整或没有地址时，回退到同一平台的单视频接口。保留原设备配置、应用身份和签名器，已完成 1080p 单集下载、解密、封装与整段音视频校验；最终应用内播放、暂停、进度跳转、切集和切换清晰度均已实测。完整对照和界面验收状态见 [验证记录](docs/validation.md)。

2026-10-14：视频模型请求保留原 JAR 其余签名，只用本项目的 `backend/hongguo_hm/` 重新生成 Helios / Medusa；批量接口已通过真实请求验证。运行不需要参考脚本。算法来源、请求绑定、错误处理和两项目同步规则见 [本地签名说明](docs/本地签名.md)。Java/JAR/SO 仍需保留。

## 打开应用

在 Finder 双击 [release/HongguoDesktop.app](release/HongguoDesktop.app)。

- 本版针对这台 Apple Silicon Mac；已包含 Python 与其库。
- Java、FFmpeg/ffprobe 使用本机安装。Finder 启动时会查找 Homebrew 的标准位置，不需要先打开终端。
- 默认保存到 `~/Downloads/HongguoDesktop/剧名_ID/`，底栏和任务面板均可更改保存位置。
- 尚未验收其他 Mac、Intel Mac 或 Windows，也未做 Apple 开发者签名、公证或独立运行时分发。

## 使用

- 搜索剧名；榜单支持全部／真人剧／漫剧／AI剧和推荐／热播／新剧榜。
- 分类选项来自平台；点击“展开全部筛选”可查看全部题材、设定、背景、排序、受众和时间条件。
- 最新上架按平台上架时间排序，可切换三种体裁。
- 有下一页时显示“加载更多”；返回列表保留筛选、内容和滚动位置。
- 详情中每集独立下载，默认 1080p，可调整清晰度；目标画质不存在时明确失败。
- 每集同时提供播放按钮；播放器支持暂停、拖动进度、上一集／下一集、选集、切换清晰度和失败重试。切换分集或清晰度从头播放，播完不自动切集。
- 播放按需读取并解密 CDN 字节范围，不生成下载任务或完整本地视频；关闭播放器、切集和退出会停止旧会话。需要永久保存时使用下载按钮。
- 下载串行排队，支持取消和手动重试。完成必须通过文件大小／哈希、解密样本及整集 FFmpeg 解码校验。
- 模型接口在点击播放／重试播放时，或下载任务实际执行时请求，不在列表或详情中预取。播放拖动进度复用当前模型和密钥，不再次签名；本地已校验下载成品仍可直接复用。
- 状态旁显示 `multi_video_model` 或 `video_model · 已回退`，悬停可查看路径与回退原因；完成后保留来源。旧任务没有记录则显示“模型接口：未记录”。
- 同一集和同一清晰度只有一个任务；已有文件必须通过匹配校验，未知文件不覆盖。
- 关闭窗口或 ⌘Q 在有任务时先确认；重启后未完成任务等待手动重试。

## 目录

| 目录 | 内容 |
| --- | --- |
| `src/` | 界面与交互、样式 |
| `src-tauri/` | 固定 IPC 命令、Python 生命周期、文件夹选择、Mac 退出保护 |
| `backend/` | App API、后台协议、下载队列和媒体处理 |
| `config/` | 复制的 App 请求和设备配置 |
| `vendor/` | 签名 JAR/SO、四份解密源码与原件对照；不向作者服务请求 |
| `.runtime/` | 复制的 Python 及库，运行包会带上 |
| `tests/` | 队列、分页、取消、文件保护、加密媒体样本及进度界面稳定性测试 |
| `docs/` | 访谈决策、架构记录、实测结果与诊断 |
| `release/` | 可双击的本机应用 |

四个原始 `.pyc` 不参与运行，也不包含在 `.app` 的 `vendor/decrypt/`。加载器只接受四个 `.py`，并校验源码 SHA-256。原 `HongguoCLI` 和 `analysis` 保留。

运行状态保存在 `~/Library/Application Support/local.hongguo.desktop/`：`settings.json`、`tasks.json` 和 `logs/`。视频旁边的 `.json` 是成品校验记录，移动视频时请一并保留。

## 开发与验证

本机已安装 Node、Rust、Java 和 FFmpeg。依赖版本由 `package-lock.json` 和 `src-tauri/Cargo.lock` 固定。

```sh
npm ci
export PATH="$HOME/.cargo/bin:$PATH"
npm run tauri -- dev
```

构建并复制到 `release/`：

```sh
./scripts/build-mac.sh
```

测试：

```sh
.runtime/python/bin/python3.11 -B -m unittest discover -s tests -v
npm run test:ui
.runtime/python/bin/python3.11 -B scripts/repro_model.py
.runtime/python/bin/python3.11 -B scripts/smoke_worker.py
.runtime/python/bin/python3.11 -B scripts/smoke_playback.py
```

`repro_model.py` 是约 2 秒的视频地址回归检查，拿不到可用地址时会明确失败。`smoke_worker.py` 访问真实 App 接口并下载、解密和校验一集，测试文件保存在 `docs/evidence/downloads/`；2026-10-13 两项均通过。平台接口可能变化，保留了修复前失败与修复后成功的独立记录。

## 请求边界

平台 base URL：`https://api5-normal-sinfonlinec.fqnovel.com`

| 功能 | 方法 | 路径 |
| --- | --- | --- |
| 搜索 | GET | `/reading/bookapi/search/tab/v` |
| 榜单 | GET | `/reading/bookapi/bookmall/cell/change/v` |
| 分类面板、筛选、最新上架 | POST | `/reading/distribution/category/landpage/v` |
| 剧详情和分集 vid | POST | `/novel/player/multi_video_detail/v1/` |
| 视频模型首选接口 | POST | `/novel/player/multi_video_model/v1/` |
| 视频模型回退接口 | POST | `/novel/player/video_model/v1/` |

海报和视频传输使用平台返回的 CDN 地址。签名器只绑定本机回环地址、随机端口并使用随机令牌。Rust 与 Python 的业务通信仍用标准输入输出；仅播放器媒体使用 Python 本机 HTTP Range 服务，绑定 `127.0.0.1` 随机端口和不可猜测的临时播放路径，不提供网页或任意 URL 代理。媒体分段只保留至多约 2 MiB 密文缓存，索引和解密密钥随播放会话释放。
