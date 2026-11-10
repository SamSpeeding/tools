# 视频为什么下载后不能播放

**当前导出样本确实有加密，取得下载 URL 不等于取得可直接播放的视频。** 本地《逆袭之实习教出金牌班，家长要换班主任》111 集共 555 条、《坠崖捡个参娃娃》74 集共 370 条清晰度记录，均返回 `encrypt_info.encrypt=true`、`encryption_method="cenc-aes-ctr"`。后者第一集的 1080p、720p、540p、480p、360p 五档还确认带有 `spade_a`。目前脚本只导出 URL 和模型信息，尚未执行原程序的解密、封装修复步骤。[脱敏观察记录](evidence/video-encryption-observation.json)

最初的结论来自已导出模型和安装器字节码。随后按用户要求，已实际下载并解密《坠崖捡个参娃娃》第 1 集，结果见下节；没有检查用户另行下载的文件，因此不把加密当作所有播放失败的唯一可能原因。

## 单集实际解密验证（2026-10-12）

已生成 [第 1 集 1080p 可播放 MP4](../outputs/decrypted-sample/坠崖捡个参娃娃_第01集_1080p.mp4)：1080×1920，时长 123.344 秒，HEVC 视频和双声道 AAC 音频，文件大小 10,680,289 字节。

- 加密原文件保留为同目录 `.enc.mp4`，10,731,638 字节，MD5 与视频模型 `file_hash` 一致。
- 在工作区独立 `.venv-decrypt` 环境中使用 Python 3.11.17、PyCryptodome 3.23.0，调用安装包原始 `unwrap_spade`、`oracle`、`decutil` 模块；执行前校验模块 SHA-256 与安装器清单一致。
- 密钥与文件匹配校验通过；3700/3700 视频样本 NAL 结构有效，2660 个音频样本已解密；FFmpeg 流复制重封装成功。
- 用 FFmpeg `-xerror` 对输出的完整视频、音轨进行解码，退出码 0、stderr 为空，处理至第 3700 帧并正常结束。此项是实际解码验证，不是仅检测 MP4 文件头。
- 未进行重新编码，未使用外部密钥服务，未把内容密钥写进命令行或验证记录。

验证记录：[decryption-verification.json](../outputs/decrypted-sample/decryption-verification.json)。执行脚本：[download_sample.py](tools/download_sample.py)、[decrypt_sample.py](tools/decrypt_sample.py)。它们固定用于这份单集样本；主入口 `hongguo.py` 仍只负责信息和地址导出。

## 原程序的处理流程

| 步骤 | 程序实际行为 | 静态证据 |
|---|---|---|
| 取得模型、选择清晰度 | `H.get_video_tracks` 返回视频轨道；`_pick_track` 选择轨道，再读取该轨道的 `encrypt_info`、`video_meta` 和 `main_url`。 | `offline_dl.py:1669–1674`；[反汇编](evidence/offline_dl.dis.txt:15031) |
| 下载 | `encrypt` 为假则直接下载为最终 `.mp4`；为真则先下载到 `.enc.mp4`，同时把期望的文件大小及文件 hash 传入下载层。 | `offline_dl.py:1680–1685`；[反汇编](evidence/offline_dl.dis.txt:15152) |
| 得到内容密钥 | 将 **对应轨道** 的 `spade_a` 交给本地 `spade_to_key`：先 Base64 解码，再运行随包的 `unwrap_v1` 字节运算。输出须是 32 个十六进制字符，即 16 字节 AES 密钥。默认模式失败于格式检查时尝试另一模式；这里没有向远端服务请求密钥。`kid` 是标识字段，不是直接拿来当 AES key。 | `unwrap_spade.py:38,90–92`；[反汇编](evidence/unwrap_spade.dis.txt:745)。`offline_decrypt.py:28–36`；[反汇编](evidence/offline_decrypt.dis.txt:319) |
| 校验模型与文件是否匹配 | 从 MP4 的 `senc` 找到 8 字节 IV 候选；用本地 `oracle.verify_key_iv` 检查解密后的视频样本长度结构。它先检查首块，再要求前两个样本通过 NAL 长度检查；不匹配则返回失败。 | `offline_decrypt.py:40–50`；[反汇编](evidence/offline_decrypt.dis.txt:443)。`oracle.py:66–97`；[反汇编](evidence/oracle.dis.txt:1121) |
| 解密音视频样本 | 找 `moov/trak` 中的视频与音频轨道，利用 `stsz`、`stsc`、`stco/co64` 计算样本位置和长度；各轨道使用自己的 `senc` 基础 IV，对每个样本的字节范围执行 AES-128-CTR，写入 `.raw.mp4`。 | `oracle.py:28–54`；[反汇编](evidence/oracle.dis.txt:526)。`decutil.py:65–99`；[反汇编](evidence/decutil.dis.txt:799) |
| 修复 MP4 封装 | 优先 FFmpeg **流复制重封装**（`-c copy`，视频标记 `hvc1`），不是重新编码。没有 FFmpeg 或其正常返回失败时，尝试纯 Python 将 `encv/enca` 改成 `hvc1/mp4a`，并将 `sinf/senc/saiz/saio` 等加密描述盒改成 `free`。成功后清理临时文件，保留最终 `.mp4`。 | `decutil.py:102–185`；[反汇编](evidence/decutil.dis.txt:1263)。`offline_dl.py:1688–1698`；[反汇编](evidence/offline_dl.dis.txt:15233) |

## 加密在哪里

**不是把整个 MP4 文件作为一个 AES 数据块解密。** 原程序仍然直接读取 MP4 的目录和样本表，只改写样本表指定的视频/音频数据区，也就是媒体负载中的对应样本。它对每个样本完整范围执行 CTR 运算；没有在这个解密路径中实现通用的“一个样本内部部分明文、部分密文”子样本表处理。

每条轨道有自己的基础 IV，每个样本重新建立 CTR 状态，并随样本序号递增。故不能简单把 `.mp4` 改名、对整个文件执行一次 AES、或只用 FFmpeg 改封装来代替内容解密。加密内容解开后，容器中仍可能保留“此轨道已加密”的标记，所以原程序还专门做了最后的封装修复。[`_decrypt_track`](evidence/decutil.dis.txt:799)、[`strip_cenc`](evidence/decutil.dis.txt:1263)

## 是否离线，Mac 需要什么

拿到匹配的 `spade_a` 和完整加密文件后，这条解密路径是本地运算。`oracle` 的名字不代表在线密钥服务：这里调用的是本地解析与验证函数；同模块中的 ADB/设备内存分析工具没有被该解密调用链执行。目录名叫 `frida` 也不代表正常离线解密必须连接手机或启动 Frida。

主要依赖是 Python、提供 `Crypto.Cipher.AES` / `Crypto.Util.Counter` 的 PyCryptodome，以及可选的本机 FFmpeg。安装器清单包含 PyCryptodome 3.23.0；FFmpeg 查找函数区分 Windows 的 `.exe` 和其他平台的可执行文件，并会搜索 PATH，因此核心实现没有必须调用 Windows 加密 API 的证据。[FFmpeg 查找逻辑](evidence/decutil.dis.txt:158)

最初本机检查结果：macOS ARM64，主项目虚拟环境 Python **3.14.3**，其中**未发现 `Crypto` 模块**；PATH 中已有 `/opt/homebrew/bin/ffmpeg` 和 `ffprobe`。随安装器提取的 Python 字节码是 **CPython 3.11** 格式，不能直接作为 3.14 环境的模块导入。[初始环境记录](evidence/video-encryption-observation.json)

单集验证已另建 `.venv-decrypt`（Python 3.11.17 + PyCryptodome 3.23.0），运行时保存在工作区 `.runtime/python`，没有替换系统 Python 或主导出脚本环境。

## 已知限制

这套代码针对它支持的 `unwrap_v1` 与 MP4 布局，不足以证明支持所有加密版本。源码里的“可能是 ver2/AES-GCM”是失败提示，不能据此认定某次失败一定属于该算法。当前样本元数据明确声明的是 `cenc-aes-ctr`。

最终验证主要是视频样本的 NAL 长度结构统计；音频记录已解密样本数，默认流程没有做完整音视频解码回放测试。部分视频样本校验异常时原程序还可能返回产物并警告。另有 `bytevc2` 编码兼容性警告分支，因此“解密完成”与“所有播放器均可播放”也不是同一项保证。本次所查第一集模型的编码字段是 `bytevc1`。[校验逻辑](evidence/offline_decrypt.dis.txt:558)、[编码兼容分支](evidence/offline_dl.dis.txt:15081)

文档和验证记录不包含实际内容密钥或 `spade_a` 值。
