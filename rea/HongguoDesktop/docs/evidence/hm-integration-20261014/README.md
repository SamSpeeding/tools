# Helios / Medusa 集成验收

2026-10-14，macOS ARM64。用户批准把前轮“固定原设备 + 原请求 + JAR 其余签名 + 本地 H/M”接入桌面和 CLI，并要求不在运行时调用参考脚本。

## 实现与来源

两个项目分别新增 `hongguo_hm/`（桌面位于 `backend/`），两份内容相同，约 34 KiB Python 源码 + 81,936 字节数据表。模块只依赖标准库。高层参数校验、Helios、protobuf、Medusa 封装按本项目接口整理；保留并精简已审计的 v3 运算，删除逆运算、无关签名、网页、插件、下载和设备生成代码，将大表保存为数据文件。

代码不导入参考脚本，不读取实验目录，不使用远程签名服务。不是重新发明加密算法，也没有宣称完整还原原 JAR v4。输入校验只支持已验证 aid=8662；沿用实际 URL 中的原设备。详细说明与协议边界见 [本地签名说明](../../本地签名.md)、[架构决定](../../adr/0003-local-model-signatures.md)。

只修改两份 `hongguo_api.py` 的模型请求签名入口。`analysis`、原参考脚本、两项目配置、JAR/SO 和原解密材料全部核对未变。签名头重新生成，其他六个 JAR 头原样保留。桌面保留批量优先/单个回退；CLI 保留 5 个 VID 一批的行为。

## 离线验证

- [修复前测试](before-tests.log)：真实 `_api_once` 调用仍发出 `jar-helios`/`jar-medusa`，新回归断言失败，非模型路径对照通过。
- [桌面测试](desktop-tests.log)：**31/31 通过**。
- [CLI 测试](cli-tests.log)：**69/69 通过**。
- 两边均验证 **64 个独立固定向量**：4 个时间戳选择 × 16 个 f13 IV 选择，覆盖全部三个摘要分支。预期值来自 [离线生成器](generate_vectors.py)，为合成设备、固定随机输入，不是实际设备或线上签名。常规测试只读取 JSON，完全不需要参考脚本。
- 额外验证原始 URL 编码、精确正文、DID/IID 绑定、并发生成、表损坏、大小写头名、非法时间戳、缺失 JAR 时间戳时不能借用配置里的旧值，以及保持非模型路径原行为。
- [交付核对](delivery-check.json)：桌面、CLI、最终应用包的三个模块文件逐字节相同；全部桌面后台源码与最终 `.app` 一致；两项目测试、向量、说明文档相同；受保护的 125 个既有文件未变。

## 真实接口与媒体

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 桌面两剧的分集 + 倒序重复 | 4 次批量请求全成功，每集 5 档轨道；未回退 | [desktop-live.json](desktop-live.json) |
| 桌面单接口独立检查 | 取得完整可用模型 | 同上 |
| CLI 每批 5 个 VID，两次重复 | 两批均完整返回，10/10 个模型各 5 档 | [cli-live.json](cli-live.json) |
| 新 Mac 包后台搜索与详情 | 搜索返回 16 项，详情 74 集 | [bundle-smoke/result.json](bundle-smoke/result.json) |
| 新 Mac 包流式播放 | 来源为 `multi_video_model`；读取 262,144 / 4,507,067 字节即就绪 | 同上 |
| 播放跳转和全流解码 | 首段/中段 Range 与完整输出一致；FFmpeg 全量音视频解码通过；关闭后旧播放 URL 返回 404 | 同上 |
| 新 Mac 包下载 | `multi_video_model`，1080p，第 2 集，4,480,838 字节，完整解码通过 | 同上 |
| CLI 实际选集下载 | 第 2 集 1080p，视频样本 1872/1872、音频 1348，完整解码通过 | [cli-download.log](cli-download.log)、[成品摘要](delivery-check.json) |
| 最终包隔离运行 | 使用包内 Python `-I`、工作目录 `/tmp`，只导入包内模块；批量模型成功且未回退 | [final-bundle-live.json](final-bundle-live.json) |

在线模型检查沿用原 `devices.json[0]`，没有注册/换设备、更换 host 或正文类型键，没有模型缓存。探针在真实发送入口比较其余 JAR 头、URL、正文摘要和时间戳，确认只覆盖 H/M。使用生产 `models()`，桌面若回退到单接口则批量检查失败，不能把回退成功误记为批量成功。

媒体端到端检查使用应用包自己的 Python/后台和全新状态目录，证明包中运行时不依赖源码目录。之后补充了“缺失 JAR 时间戳时不借用配置值”的输入防护，离线测试后重新构建；最终包再次做隔离真实模型请求，并核对全部后台文件一致。媒体解密代码和 H/M 生成算法在两次构建间未变。

这次验证后台与打包资源，没有重新进行完整原生窗口点击验收；UI 未修改。先前的 UI 验收见项目验证记录。线上结果仅覆盖这次测试，不承诺平台跨天永远接受签名。

## 复验命令

在 `HongguoDesktop/` 下：

```sh
.runtime/python/bin/python3.11 -B -m unittest discover -s tests -v
.runtime/python/bin/python3.11 -B scripts/probe_local_hm.py --client desktop --output /tmp/hm-desktop.json
.runtime/python/bin/python3.11 -B scripts/probe_local_hm.py --client cli --output /tmp/hm-cli.json
./scripts/build-mac.sh
.runtime/python/bin/python3.11 -B scripts/smoke_local_hm.py --output /tmp/hm-new-smoke
```

媒体 smoke 的输出目录必须尚不存在，避免已有文件/任务被误算为新下载成功。CLI 单独测试在 `HongguoCLI/` 下执行 `.venv/bin/python -B -m unittest discover -s tests -v`。

原命令行完整下载验证使用：

```sh
.venv/bin/python -B hongguo.py --series-id 7689863296106646590 --download 2 --quality 1080p --download-dir ../HongguoDesktop/docs/evidence/hm-integration-20261014/cli-downloads
```

`generate_vectors.py` 是一次性的离线来源核对工具，会读取指定参考文件；不要把它放进应用启动/安装/常规测试链路。三个生产模块文件均无此依赖。Mac 打包过程见 [build.log](build.log)。
