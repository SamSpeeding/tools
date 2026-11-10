# 现有脚本脱离 Python、迁移到 PHP 的可行性

调研日期：2026-10-13。范围：官方资料与现有源码核对；仅分析，不实现移植、不安装依赖、不向平台发送业务请求，不改动 `analysis`、业务代码和原 `.pyc`。本机只读查询显示 `/opt/homebrew/bin/php` 为 PHP 8.3.30 CLI NTS；本轮没有执行 PHP 算法探针或业务测试。

**PHP 可以承担当前 Python 的全部业务职责，迁移完成后可以去掉 Python；但现有脚本仍需 Python，PHP 版本尚未实现。** 最少改动的运行依赖会变成 PHP CLI（所需扩展）+ Java + 现有签名文件 + FFmpeg/ffprobe，必要时再配独立的网络传输组件。这个判断来自当前调用链和下述官方能力，不等于整条链已经实测成功。依据：[业务请求](../hongguo_api.py)、[签名器](../hongguo_signer.py)、[下载与校验](../hongguo_download.py)。

## 各部分能否替代

| 当前职责 | PHP 对应方案 | 当前判断 |
|---|---|---|
| 搜索、详情、视频模型、分页、选集 | PHP 业务逻辑、JSON、ext-curl | 能力具备；需移植和验收 |
| 本地签名器 | `proc_open()` 启动 Java，通过本机 HTTP 调用 `/sign` | 能力具备；保留现有 Jar/SO/BIN |
| CDN 下载、重试、大小和哈希检查 | cURL 下载至文件、文件操作、摘要函数 | 能力具备；需保持现有校验与失败处理 |
| 模型参数恢复密钥 | 字节字符串、Base64、位运算 | 需移植 `unwrap_spade.py` |
| MP4 解析、样本解密、加密标记清理 | 二进制文件操作、`pack/unpack`、OpenSSL AES-CTR | 能力具备；不能只换启动命令 |
| 重封装、媒体信息和全片解码检查 | 启动 FFmpeg/ffprobe | 保留外部程序 |

能力来源：[cURL 要求](https://www.php.net/manual/en/curl.requirements.php)、[proc_open](https://www.php.net/manual/en/function.proc-open.php)、[PHP 字符串](https://www.php.net/manual/en/language.types.string.php)、[pack](https://www.php.net/manual/en/function.pack.php)、[openssl_decrypt](https://www.php.net/manual/en/function.openssl-decrypt.php)。业务边界以[当前下载调用路径](../hongguo_download.py)及[四份恢复源码](../vendor/decrypt/)为准。

## Jar/SO 的关系不会因 PHP 改变

现有链路可以替换为：**PHP → Java/Jar → unidbg → Android SO → 签名头**。PHP 通过本机接口取签名后，再直接向平台发请求。SO 由 Jar 内的 Android 模拟环境加载，并非普通 macOS/Windows 动态库；不应设想用 PHP FFI 直接装入就能运行。依据：[LocalSigner](../hongguo_signer.py)、[FqTrace 反汇编](../../analysis/evidence/FqTrace.javap.txt)中的 `AndroidEmulatorBuilder.for64Bit`、`AndroidResolver` 和 `VM.loadLibrary`；文件类型另见[既有核对证据](evidence/2026-10-13/node-feasibility.json)。

**Jar/SO 负责签名，媒体解密在恢复的 Python 源码中。** 去掉 Python 必须移植实际使用的 MP4/密钥/解密逻辑。原模块里的独立 ADB 采集、dump 分析工具不在正常下载路径；若只做下载产品，可不把这些未调用工具带入成品。若要求四份模块的所有独立功能等价，则须另行覆盖。依据：[hongguo_download.py](../hongguo_download.py)、[oracle.py](../vendor/decrypt/oracle.py)、[extract_keybox_pairs.py](../vendor/decrypt/extract_keybox_pairs.py)。

## PHP cURL 能否直接请求

**可能可以，目前没有证据证明不行；也不能未经验证就保证直接替换成功。** PHP ext-curl 依赖 libcurl，具体 TLS 行为取决于实际构建和 TLS 后端；普通 PHP cURL 不自动具有当前 `curl_cffi` 的浏览器 TLS/HTTP2 指纹模拟能力。来源：[PHP cURL 依赖](https://www.php.net/manual/en/curl.requirements.php)、[curl TLS 后端对照](https://curl.se/docs/ssl-compared.html)、[curl_cffi 官方说明](https://github.com/lexiforest/curl_cffi#features)。

当前[源码](../hongguo_api.py)使用 `impersonate="chrome"`，也明确记录：历史成功试验同时更改了传输和设备参数，无法归因于其中一个因素。因此 PHP 和 Node 面临的是同一个尚未隔离验证的问题，换语言不会自动消除或增加平台指纹要求。

将来若实施，应先以**相同设备配置、请求参数和待签名字节**验证普通 PHP cURL 的搜索、详情、模型响应；注意时间戳和签名时效。只有确认普通传输不能满足条件时，才评估从 PHP 启动独立 curl-impersonate CLI。该项目提供独立二进制发行，不要求用 Python 包作为入口；具体版本、架构、证书和运行结果仍须验收。来源：[项目安装说明](https://github.com/lexiforest/curl-impersonate/blob/main/docs/install.rst)。

## 解密和二进制数据没有 Python 专属限制

PHP 的 string 可以容纳原始二进制数据；`ord/chr`、`pack/unpack`、`fread/fseek` 足以表达现有字节变换和 MP4 结构读取。文件应使用二进制模式，检查读取长度与边界。这个能力判断不代表已有完整 PHP MP4 实现。来源：[字符串](https://www.php.net/manual/en/language.types.string.php)、[pack](https://www.php.net/manual/en/function.pack.php)、[unpack](https://www.php.net/manual/en/function.unpack.php)、[fread](https://www.php.net/manual/en/function.fread.php)、[fseek](https://www.php.net/manual/en/function.fseek.php)。

PHP OpenSSL 提供 `openssl_decrypt()`，其算法列表可包括 `aes-128-ctr`；移植时使用 `OPENSSL_RAW_DATA` 输入原始密文，并传入正确长度的**原始密钥和 IV 字节**，不能直接把十六进制文本当密钥。目标 PHP/OpenSSL 构建仍需核对算法可用性。来源：[openssl_decrypt](https://www.php.net/manual/en/function.openssl-decrypt.php)、[openssl_get_cipher_methods](https://www.php.net/manual/en/function.openssl-get-cipher-methods.php)。

当前[decutil.py](../vendor/decrypt/decutil.py)每个样本重新建立 CTR，起点是 `(base_iv64 + sample_index) << 64`，音轨、视频轨分别处理。PHP 普通 int 没有 128 位能力，不能照抄这个整数表达式；可把高 8 字节 IV 用逐字节进位计算，再拼接低 8 字节零构成 16 字节计数器，并对越界明确失败。**因此不必强制引入 GMP。** 这是等价实现方案推导，尚未做 PHP 向量对照。整数范围依据：[PHP integers](https://www.php.net/manual/en/language.types.integer.php)。

现有验收还包括样本表、音视频解密、加密标记清理、重封装与完整解码；不能以“OpenSSL 解出一块数据”替代成品验收。应沿用[合成媒体夹具](../tests/media_fixture.py)及[源码媒体测试](../tests/test_recovered_media.py)的比较条件。当前已验证的格式范围仍是 Python 版本的 CENC AES-CTR、HEVC 和 AAC。

## 请求字节和大整数的迁移细节

1. **剧 ID/vid 统一保留字符串。** 当前约 `7.7×10^18` 的 ID 小于 64 位有符号整数上限，在 64 位 PHP 中可以精确表示；不能把 JavaScript `Number` 的 53 位限制套给 PHP。但为接口、网页和持久化一致，应按字段规范转为字符串，不经过 float。`JSON_BIGINT_AS_STRING` 只对超出 PHP 整数范围的整数生效，不会自动把全部较大 ID 转成字符串。依据：[integers](https://www.php.net/manual/en/language.types.integer.php)、[PHP JSON scanner 源码](https://github.com/php/php-src/blob/PHP-8.3/ext/json/json_scanner.re)。
2. **MP4 无符号 64 位值单独处理。** PHP 不提供 unsigned int；超出有符号范围的 IV 不能直接当 int 加法。可保留字节或拆成高低段。文件偏移进入 `fseek` 前，必须验证不超出平台整数及实际文件边界。依据：[integers](https://www.php.net/manual/en/language.types.integer.php)、[fseek](https://www.php.net/manual/en/function.fseek.php)和[现有解析器](../vendor/decrypt/oracle.py)。
3. **签名 URL 与实际发送 URL 相同。** 当前空格编码为 `%20`；`http_build_query()` 默认会使用 `+`，应明确采用 `PHP_QUERY_RFC3986` 或逐值 `rawurlencode()`，保留参数顺序、字符串类型和显式 `&` 分隔。来源：[http_build_query](https://www.php.net/manual/en/function.http-build-query.php)、[rawurlencode](https://www.php.net/manual/en/function.rawurlencode.php)、[build_url](../hongguo_api.py)。
4. **摘要与发送共用同一份 JSON 字节。** `JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES` 可以接近当前序列化选择，但并非通用跨语言规范化方案；对象/数组、浮点数、换行字符及键序仍需对照。先确定 UTF-8 请求体，再对它计算大写 MD5 并原样发送。不要再次序列化，也不要用 `JSON_NUMERIC_CHECK` 把 ID 字符串变回数字。来源：[JSON 常量](https://www.php.net/manual/en/json.constants.php)、[当前请求摘要实现](../hongguo_api.py)。

## 进程与长任务应如何安排

`proc_open()` 自 PHP 7.4 起接受命令参数数组，以不经过 shell 的方式启动进程；可指定工作目录、环境及标准输入输出。Windows 字符串命令还涉及 `bypass_shell` 和引号规则，数组参数也有目标程序参数解析约定。建议沿用现在的独立参数、固定工作目录、就绪检查、超时及退出清理，不拼接一长串 shell 命令。来源：[proc_open 正文](https://www.php.net/manual/en/function.proc-open.php)。

Java/FFmpeg 的输出必须持续消费或重定向至文件；关闭管道后再回收进程。Windows 下 `stream_select()` 不能用于 `proc_open()` 返回的描述符，这是真实的平台差异，但不等于 PHP 无法在 Windows 启动子进程。可让签名器写文件、继续通过本机 HTTP 通信；其他进程的进度、取消和错误读取需设计并实测。来源：[proc_open 示例](https://www.php.net/manual/en/function.proc-open.php)、[stream_select 的 Windows 说明](https://www.php.net/manual/en/function.stream-select.php)。

**长期下载适合独立 PHP CLI worker。** 网页请求负责创建任务、查询进度、取消和取得成品。把整集下载/解密绑在一个 FPM 请求上，会涉及执行时间、FPM 请求终止和客户端断开行为；仅 `set_time_limit(0)` 不构成可靠的任务管理。队列、状态落盘、失败恢复和进程生命周期仍需实现。来源：[set_time_limit](https://www.php.net/manual/en/function.set-time-limit.php)、[FPM 配置](https://www.php.net/manual/en/install.fpm.configuration.php)、[连接处理](https://www.php.net/manual/en/features.connection-handling.php)；worker 分工是据此提出的架构建议。

`php -S` 默认是单个单线程服务进程，请求阻塞会影响其他请求；用于测试的多 worker 功能不支持 Windows。官方定位是开发、测试或受控演示。因此不建议用它直接承担正式桌面产品的长下载任务，调高超时不能解决调度问题。来源：[PHP 内建服务器](https://www.php.net/manual/en/features.commandline.webserver.php)。

## 脚本、网页和双平台桌面如何取舍

| 场景 | 调研判断 |
|---|---|
| PHP 命令行脚本 | 技术可行；无需 Apache/Nginx，但仍须准备 PHP、扩展和外部组件，重写业务与媒体逻辑 |
| 已有 PHP 网站或管理后台 | 合理选择；界面/API 与独立任务 worker 分工，能沿用团队经验 |
| 本地网页工具 | 可行；搜索请求和长任务分离，浏览器领取已生成成品 |
| 新建 macOS/Windows 桌面应用 | 可行；需桌面外壳、PHP runtime、扩展及 Java/FFmpeg 的分平台打包，不会仅因换 PHP 就自然减少依赖 |

以上是结合已有代码和官方能力做出的适用性判断，未比较 PHP/Node 的性能或安装包大小。若团队熟悉 PHP，开发维护优势可能超过迁移成本；若主要目标是尽快把当前已通过验证的脚本做成桌面版，继续复用 Python 通常需要改动更少，这是当前项目状态的推断。

Tauri 可以把 PHP 可执行文件作为外部进程打包，并通过其 shell/Rust 端管理；所需 runtime、扩展和资源要自行提供，且按目标系统/架构验收。也存在面向 Laravel 开发者的 NativePHP Desktop，它提供静态 PHP runtime 和应用打包能力；选这种外壳仍不会自动完成当前业务移植。来源：[Tauri sidecar](https://v2.tauri.app/develop/sidecar/)、[NativePHP Desktop 官方介绍](https://nativephp.com/docs/desktop/2/getting-started/introduction)。本轮不对两者完整依赖、体积和性能作结论。

## 若日后决定实施，哪些结果才算完成

1. PHP 独立启动和停止 Java/FFmpeg，覆盖错误、超时、取消及 macOS/Windows 进程行为。
2. 请求 URL、JSON 字节及摘要与现有基线对照，再隔离验证普通 cURL 的搜索、详情、模型兼容性。
3. 密钥恢复和 CTR 向量对照通过；合成加密 MP4 的音视频解密、结构处理、解码后哈希与基线一致。
4. 搜索分页、选剧选集、主备地址、失效地址刷新、下载完整性及成品检查完整通过。
5. 在没有 Python 的干净目标环境运行成品，检查实际启动的子进程和加载路径，证明没有偷偷回退到 Python。

**本轮完成的是可行性调研，未执行这些验收。** 既有 56 项测试和真实下载记录属于 Python 版本，不能转算为 PHP 迁移成功；本机已安装 PHP 也只说明有命令行解释器。
