# 原程序 1.0.0.72 → 1.0.0.73 逆向对比

日期：2026-10-14。输入由用户指定：`/Users/tt/Downloads/HongguoDownloader-Setup (1).exe`。旧样本为 `/Users/tt/Desktop/rea/HongguoDownloader-Setup.exe`。

## 结论

**新版确实修改了视频模型链路，但采取的是直接改用单个 `video_model`，没有把 `multi_video_model` 修复后继续使用。** 这可能恢复原程序的下载能力，不能因此断言新版整个程序仍不可用；本轮没有在 Windows 上安装运行新版。

三个实际模型入口 `hongguo.get_video_urls`、`hongguo.get_video_tracks`、`offline_dl._video_model` 都从批量路径改为单个路径。签名器、SO、设备池、设备注册/刷新相关逻辑没有实质更新。根据用户后续指示，确认这一点后已恢复原先隔离实验，见 [批量接口实验结论](../../HongguoDesktop/experiments/batch-model-20261014/README.md)。新包逆向和线上实验是两套独立证据。

## 安装包身份与覆盖

| 项目 | 旧包 | 新包 |
|---|---|---|
| 内置 `version.txt` | 1.0.0.72 | 1.0.0.73 |
| 安装包 SHA-256 | `9d77a2548cc1bde92c4a269a3f482655b4f5fc538421f328af8d959d6739b592` | `df7cb1fae6f0e8637fb630d85f8205b9d2b3ae59cde7c83bf6e37f67af83612f` |
| 安装格式 | 已有 Inno 样本 | Inno Setup 6.7.0 |

REA 打开用户指定的新包，并静态检查 PE 资源，证据 `ev_219c7550132c129c9d289511ed76e139fdd35a1f14449a2501cfd654f6863376`，完整记录见 [REA PE 资源](evidence/rea-pe-resources.json)。Python 字节码使用 `marshal/dis` 辅助分析，没有声称它是 REA 原生反编译结果。

复用已有 Inno 解析器，把 31 个选定程序文件提取到本目录 `extracted/`，每个文件实际内容的 SHA-256 均与安装包内声明一致。比较 3,966 个有效清单项：1,514 项 hash 变化，2,452 项相同，没有已映射路径增删。这个数量不能当作功能变更数，大量 pyc 因构建路径变化而改变字节。

明确边界：解析器没有可靠映射一条 `python/pythonw.exe` 记录（location=8192），未纳入比较；Python/Java/FFmpeg 依赖大部分只比较包内清单 hash，没有全量解包审计。应用自身 18 个 pyc 全部完成递归代码比较。输入安装包和冻结 `analysis/` 未写入。

## 模型链路的实质改动

| 项目 | 1.0.0.72 | 1.0.0.73 |
|---|---|---|
| 模型 URL 路径 | `/novel/player/multi_video_model/v1/` | `/novel/player/video_model/v1/` |
| 请求目标 | `mixed_video_id_map: {"1": [vid, ...]}` | `video_id: vid` |
| 模型位置 | `data[vid].video_model` | `data.video_model` |
| 取多个 VID | 最多 5 个合成一条请求 | 遍历未缓存 VID，逐个请求 |
| `get_video_tracks(..., batch_size=5)` | 参数影响分组大小 | 签名保留，但函数不再用它分组 |
| 失败后改接口 | 没有单个回退 | 直接使用单个接口，不先试批量 |
| `biz_param` 九项 | 原值 | 不变 |
| 缓存/下载调度/重试 | 原行为 | 保留 |

`_STRIKE_PATHS` 中的模型路径同步由批量换为单个，其余通用请求、签名、认证刷新和异常处理函数不变。

证据：[完整代码对象差异](evidence/bytecode-diff.json)、[hongguo 指令差异](evidence/bytecode/app__hongguo.pyc.diff)、[新版 get_video_tracks](evidence/bytecode/app__hongguo.pyc.new.txt#L1625)、[下载/播放调用链专项](download-diff.md)。函数名和源行号来自 pyc；这些反汇编不是原始 Python 源码。

为避免仅凭 URL 字符串判断，还对原始函数字节码做了**离线受控回放**：不执行模块顶层，用内存缓存和假 API 响应调用新旧两版 `get_video_tracks/get_video_urls`。每次输入 6 个未缓存 VID，旧版两函数分别发出 2 次假 API 调用，新版分别发出 6 次；再次输入相同 VID 都为 0 次。网络请求数为 0。见 [回放证据](evidence/model-functions-offline-replay.json)、[回放脚本](replay_model_functions.py)。

完整下载调用链是 `server._dl_worker → offline_dl.download_series → EpisodePool → hongguo.get_video_tracks`；单集重取也调用 `get_video_tracks`。因此，虽上层仍保留“一次预取 5 集”的队列概念，新版底层已变成每集一次单模型请求。

## 签名与设备是否更新

**没有发现这一方向的实质修复。** JAR、`libmetasec_ml.so`、`libc++_shared.so`、`ms_16777218.bin` 和 69 条 `devices.json` 均字节相同；设备生成、读取、轮换，以及 `refresh_session`、签名调用链均相同。

`config.json` 只换了基础 `device_id/iid/cdid`。默认启动会从随包设备池随机选定一条会话设备，请求时覆盖这三项，所以这不等于默认请求真正换了新设备。我们项目固定使用池第 0 项，和原程序随机选定一项是既有实现差异，并非本次新版增加。

详见 [设备与签名专项](device-signing-diff.md)。没有新注册接口、没有新刷新算法，也没有从这次更新恢复出新的有效设备生命周期。

## 其他变化及未变化项

18 个应用 pyc 中，排除构建路径及源行位置，直接变化集中在 `hongguo`、`offline_dl`、`_integrity`：前两项是上述模型逻辑、网页预览适配；后者为模块级完整性常量变化。其他 15 个模块未发现代码结构变化。

另一项业务改动为网页预览读取 `publicVideoSeo`，校验 VID 并构造 `/video/public/{vid}/360p.mp4`，见 [专项说明](download-diff.md)。它不属于当前项目限定的 App 平台 API，未带入项目。

## 已回答与仍未知

- 已回答：新包版本、核心函数改动、请求/响应契约、取多集时的请求数量、签名与设备有无更新。
- 已回答：新版使用单个接口处理原批量入口，未继续调用批量接口来证明批量恢复。
- 仍未知：作者实际遇到的报错与修改动机、平台内部拒绝原因、新版 Windows GUI 当前在线运行表现。
- 线上实验的结论另存，不把静态分析冒充平台实测；当前应用代码、配置及二进制未因本次研究更改。

复查入口：[提取与清单比较](extract_compare.py)、[字节码比较](compare_bytecode.py)、[完整安装包差异](evidence/installer-diff.json)。
