# 现有脚本脱离 Python、迁移到 Node.js 的可行性

调研日期：2026-10-13。范围：当前 CLI 的搜索、详情、视频模型、选集下载、解密、成品校验；不实现迁移，不改动 `analysis`、现有业务代码和保留的 `.pyc`，本次没有向平台发送业务请求。

**可以把当前业务完整移植到 Node.js，从发布成品中去掉 Python；但当前脚本仍然需要 Python，且工作量不只是把 Jar/SO 的调用者换成 Node。** 搜索协议、结果处理、下载管理，以及四份 Python 源码中的媒体处理功能，都要有对应实现。底层签名可继续复用 Java + unidbg + SO；FFmpeg/ffprobe 继续负责重封装与完整解码检查。依据：[当前依赖说明](../README.md)、[接口实现](../hongguo_api.py)、[签名进程管理](../hongguo_signer.py)、[下载实现](../hongguo_download.py)。

## 已确认与尚未验证

| 判断 | 证据与状态 |
|---|---|
| 当前正常运行已不依赖保留的原 `.pyc` | 已完成；当前入口强制加载四份 `.py`。这不等于不需要 Python。见 `load_decrypt_modules()` 和 `preflight()`。 |
| 业务没有必须由 Python 执行的独有能力 | 从当前源码及下述 Node 官方能力推导；未发现 Python 专属算法或无法替代的运行时机制。 |
| Node 可启动 Java/FFmpeg，进行 AES-CTR、二进制解析和摘要计算 | 官方 API 支持；本机还完成了下文限定范围的离线探针。 |
| 换成 Node 后搜索、下载、解密整条链已经成功 | **尚未实现、尚未验证。** 既有 56 项测试和真实下载证明的是 Python 版本。 |
| Node 原生 `fetch` 可直接替换现有平台传输 | **未确认。** 当前使用浏览器指纹传输，不能只比较 URL 和请求头。 |
| macOS 和 Windows 发布包均可直接运行 | **未验收。** 原生库、Java、FFmpeg、Node 或 Rust 程序均需对应系统和架构版本。 |

## 各部分如何迁移

| 当前职责 | 当前实现 | Node 方案 | 迁移后需要的额外组件 |
|---|---|---|---|
| 参数、选剧选集、分页、去重、详情和模型整理 | [hongguo.py](../hongguo.py)、[hongguo_api.py](../hongguo_api.py) | TypeScript/JavaScript 业务逻辑 | 无 Python 依赖 |
| URL、JSON 请求体、MD5 请求摘要 | `build_url()`、`_req_headers()`、`_api_once()` | 确定性序列化、`Buffer`、`node:crypto` | 无 Python 依赖 |
| 启动和关闭本地签名器 | [hongguo_signer.py](../hongguo_signer.py) | `child_process.spawn()`；保留本机 HTTP `/sign` 调用 | Java、原 Jar、两份 SO、BIN |
| 平台 HTTPS 请求 | `curl_cffi.Session(impersonate="chrome")` | 选择并验证非 Python 的等价传输组件 | 可能需原生 libcurl-impersonate 或独立二进制 |
| CDN 流式下载、主备地址、大小/哈希检查、完成记录 | [hongguo_download.py](../hongguo_download.py) | Node 流、文件操作、摘要与重试逻辑 | 候选为 Node HTTP/fetch；需单独实测 |
| 从模型参数恢复密钥 | [unwrap_spade.py](../vendor/decrypt/unwrap_spade.py) | 按现有源码移植 Base64 和字节运算 | 无 Python 依赖 |
| MP4 样本表、IV、密钥验证、音视频样本解密、清除加密标记 | [oracle.py](../vendor/decrypt/oracle.py)、[decutil.py](../vendor/decrypt/decutil.py) | `Buffer`、`BigInt`、`node:crypto`，移植解析和验证逻辑 | 无 PyCryptodome 依赖 |
| 重封装、媒体信息、全片解码检查 | `playable_file()` 的外部命令 | `spawn()` 调用本机程序 | FFmpeg、ffprobe |

Node 官方提供非 shell 的子进程启动及生命周期事件、带指定算法和 IV 的解密接口、64 位大端整数读写与二进制缓冲区。这些是上述替代方案的能力依据，不代表现有 Python 文件能被 Node 直接执行。来源：[child_process](https://nodejs.org/api/child_process.html#child_processspawncommand-args-options)、[crypto](https://nodejs.org/api/crypto.html#cryptocreatedecipherivalgorithm-key-iv-options)、[Buffer](https://nodejs.org/api/buffer.html#bufreadbiguint64beoffset)。

`extract_keybox_pairs.py` 的 dump 扫描/报告功能，以及 `oracle.py` 内的 ADB 采集工具，目前不在正常下载调用路径中。现在仍会因模块导入关系加载它们；Node 迁移若只覆盖当前下载产品功能，可以只移植实际使用的能力，不必把未调用的研究工具装进产品。若要求四份文件的全部独立 CLI 功能也等价，则要另行移植。依据：[下载调用路径](../hongguo_download.py)、[oracle](../vendor/decrypt/oracle.py)、[keybox 工具](../vendor/decrypt/extract_keybox_pairs.py)。

## SO 和 Jar 的实际关系

现有结构是：业务程序启动 Java → Jar 中的 unidbg 建立 Android 模拟环境 → 加载 Android SO 计算签名 → 业务程序通过本机 HTTP 取得签名头。Python 主要负责进程管理和调用，并没有把 Android SO 直接装进自身进程。依据：[LocalSigner](../hongguo_signer.py)、[FqTrace 反汇编](../../analysis/evidence/FqTrace.javap.txt) 中的 `AndroidEmulatorBuilder.for64Bit`、`AndroidResolver`、`VM.loadLibrary`。

本机 `file` 核对两份 SO 均为 **ELF 64 位 ARM aarch64**。这是 Android 原生库，不是 macOS 的 `.dylib` 或 Windows 的 `.dll`；即便 Mac 也是 ARM64，也不能把它视为普通本机库直接 FFI 调用。unidbg 提供 ARM32/ARM64、JNI 和系统调用模拟，正是在补足这层环境。来源：[本机文件类型证据](evidence/2026-10-13/node-feasibility.json)、[unidbg 官方项目](https://github.com/zhkl0228/unidbg#features)。

Jar 静态清单中包含 85 项原生组件，能看到 Windows 64 位及 macOS ARM64 的 Unicorn/JNA 等库；这说明已有跨平台组件基础，不能替代 Windows 的实际启动和签名验收。清单见同一份本机证据的 `jar_native_members`。

因此，最少改动的 Node 方案是保留 Java 签名进程，通过本机 HTTP 调用；不需要为了去掉 Python 同时重写签名算法。媒体解密仍需移植上表中的 Python 逻辑，**Jar/SO 不是现成的“搜索到成品视频”总接口**。保留本地服务也不表示增加了远端服务；它是两个本机进程之间的调用方式。

## 最需要先验证的是请求传输

当前平台请求显式使用 `curl_cffi` 的 `impersonate="chrome"`。其官方说明覆盖 TLS/JA3 和 HTTP/2 指纹；Node 内置 `fetch` 基于 Undici。“提供 fetch API”不能推出“发送相同的 Chrome 握手和 HTTP/2 特征”。所以不能未经验证就承诺 `fetch` 或 Axios 可直接替换。来源：[本地传输配置](../hongguo_api.py)、[curl_cffi 官方说明](https://github.com/lexiforest/curl_cffi#features)、[Node fetch](https://nodejs.org/api/globals.html#fetch)。

当前源码注释还记录：过去的成功探测同时更改过 HTTP 传输和设备参数，没有控制变量证明“必须依赖 Chrome 指纹”。准确结论是：**存在尚未隔离验证的兼容性条件**，既不能说普通 fetch 必然失败，也不能说必然成功。

可验证的非 Python 方案有两类：

- **独立 curl-impersonate 二进制**：由 Node 启动。官方安装文档列出 macOS、Windows、Linux 预编译版本，并区分独立 CLI、动态库和静态库。项目打包时还需核对具体版本的架构、证书配置与平台运行结果。来源：[官方安装文档](https://github.com/lexiforest/curl-impersonate/blob/main/docs/install.rst)。这与调用 Python 包附带的 `curl-cffi` 命令不同，后者不能作为去掉 Python 的证明。
- **Node 绑定 impers**：curl_cffi 官方 README 指向同维护者的 TypeScript 项目；通过 Koffi 加载 libcurl-impersonate。其 README 明确为 alpha，默认首次运行会下载原生库，并提供 `LIBCURL_PATH`。`package.json` 声明的运行依赖为 Koffi，没有直接声明 Python；本次未安装或审计所有原生构建回退流程，不能据此承诺每个平台构建阶段都不需要 Python。产品运行可考虑固定并随包提供已验收的库，避免依赖首次启动下载。来源：[impers README](https://github.com/lexiforest/impers#readme)、[package.json](https://github.com/lexiforest/impers/blob/main/package.json)。

这两类组件都仍需与当前配置做请求和响应对照；最新指纹版本也不自动等于当前脚本使用的版本。只替换 Python 这一目标不要求采用作者的云签名、商业指纹接口或其他远端代理。

## 移植时不能忽略的字节细节

以下要求来自当前源码；基础行为已由下节探针核对，完整业务等价仍待迁移测试。

1. **剧 ID、vid 保持字符串。** 现有真实 ID 约为 `7.7×10^18`，超过 JavaScript 安全整数范围；不能先用 `Number` 解析再转字符串。如果响应中的关键 ID 仅以 JSON 数字返回，需无损解析或取对应字符串字段，普通 `JSON.parse()` 后转换可能已经丢失精度。
2. **64 位 MP4 偏移和 IV 用 `BigInt`。** 当前包含 `co64` 和大端 64 位字段；Python 大整数到 JavaScript 普通位运算的机械翻译会截断。转成 Buffer 下标前还要检查实际文件长度及可安全表示范围。
3. **每个样本的 CTR 起点必须相同。** 当前计算为 `(base_iv64 + sample_index) << 64`，每个样本重新创建 AES-CTR；不是对整个 MP4 使用一次连续解密。视频轨、音频轨还各自读取其 IV。依据：`_decrypt_track()`、`decrypt_av()`。
4. **签名 URL 必须与发送 URL 一致。** 当前 Python `quote(..., safe='')` 使用 `%20`，且保留构造顺序；`URLSearchParams` 通常把空格变成 `+`，原样 `encodeURIComponent` 对 `!'()*` 也不等价。需要明确实现相同编码规则，并防止发送库再次改写 URL。
5. **请求摘要针对实际发送的 UTF-8 字节。** 当前先生成无多余空白的 JSON 字节，再算大写 MD5 填入 `x-ss-stub`；Node 应对同一份 Buffer 计算摘要并发送，不要让请求库二次序列化。
6. **成品验收不能缩减。** 保留下载大小/哈希、音视频样本处理、MP4 标记清理、重封装和全片解码；继续保留不支持格式时明确失败的范围限制。当前已验证范围是 CENC AES-CTR、HEVC 视频和 AAC 音频。

对应源码：[请求构造](../hongguo_api.py)、[MP4 解析](../vendor/decrypt/oracle.py)、[CTR 与 MP4 标记处理](../vendor/decrypt/decutil.py)、[成品检查](../hongguo_download.py)。

## 本次离线验证

结果已保存为 [node-feasibility.json](evidence/2026-10-13/node-feasibility.json)。环境为 **Node v24.11.0 / macOS ARM64**。

- 8 组 AES-128-CTR 向量与当前 PyCryptodome 结果一致，并完成加密/解密回环；覆盖两个 64 位 base IV、样本序号 0/1/4095 和 0/17/32/1027 字节的组合。
- Buffer/BigInt 64 位读写、同一 UTF-8 JSON 的 MD5、修正后与 Python quote 相同的编码、无 shell 子进程调用均通过。
- 确认了 `URLSearchParams` 编码不等价，以及真实剧 ID 转成 `Number` 不安全；保持字符串可保留原值。

**范围仅为基础能力探针。** 本次没有用 Node 执行实际 Jar 签名、平台请求、完整 MP4 解析/解密或整集下载；也没有完成 Windows 测试。探针使用 Python 作为对照，不是最终无 Python 发布包的证明。

## 若用于 Tauri 桌面应用

可选结构为：Tauri 窗口与界面 → Node 业务进程 → Java 签名进程、FFmpeg 及传输组件。Node 负责迁移后的业务与媒体处理。Tauri 的 Node sidecar 指南要求额外打包 Node 应用或运行时，**Tauri 本身不会赠送一个 Node 运行环境**；用户可以不单独安装 Node，但运行时仍会随应用分发。来源：[Tauri Node sidecar](https://v2.tauri.app/learn/sidecar-nodejs/)。

如果最终目标是减少运行时层数，也可以把业务和媒体处理移到 Rust，由 Tauri 的 Rust 端直接启动 Java/FFmpeg；这样运行时可以同时去掉 Python 和 Node。Tauri 官方支持从 Rust 启动外部程序，并要求针对目标平台/架构准备 sidecar。这个方案的业务迁移与传输适配仍然要做，不能仅凭架构推导包体大小或全部功能已可用。来源：[Tauri 外部程序](https://v2.tauri.app/develop/sidecar/)。

## 最小验收顺序

1. **签名器独立启动**：用 Node 管理现有 Jar，验证就绪探测、本机 token、工作目录、超时、取消和退出清理；业务进程中不启动 Python。
2. **请求兼容性**：先以固定输入比较 URL、请求体字节、MD5 和参数；再在允许的在线验证中，以相同设备配置检验候选 HTTP 传输的搜索、详情、模型，隔离传输差异。
3. **本地媒体等价**：移植实际所需算法，对已有自测向量、边界输入和合成 HEVC/AAC 加密夹具做 Python/Node 对照；比较样本结果及解码后音视频哈希。可复用 [既有测试](../tests/test_recovered_media.py) 和 [媒体夹具](../tests/media_fixture.py) 的验收条件。
4. **整条链**：搜索分页、选剧、选集、模型、主备 URL、下载校验、解密和完整解码；同时覆盖取消、失效地址刷新、失败记录、已完成文件识别。
5. **无 Python 发布验收**：在不含本项目 Python/venv、也无可用 Python 的干净目标环境运行，检查实际子进程和加载路径；分别验证 macOS ARM64、计划支持的 macOS Intel/Windows 架构。开发对照测试可以保留 Python，成品不得偷偷回退到它。

这些步骤通过后，才能把状态从“可迁移”改为“已经完全脱离 Python”。目前已有源码和测试使迁移具备明确依据，但尚未交付 Node 版本。
