# 1.0.0.72 → 1.0.0.73：设备、配置、签名专项静态比较

日期：2026-10-14。证据编号：`DS-20261014-73`。完整机器可读证据见 [device-signing-evidence.json](device-signing-evidence.json)。本专项只读取解包产物，通过 Python 3.11 `marshal`/`dis` 解析代码对象，未导入目标模块、运行安装器、运行签名器或发起网络请求。

## 结论

**在设备和签名这一条路径上，新版没有携带新的设备注册/刷新算法，也没有更新 JAR、SO 或随包的 69 条设备池。** `config.json` 确实变化，但只换了 `base_query.device_id`、`base_query.iid`、`base_query.cdid` 三项。随包设备池有效的默认路径会覆盖这三项，所以不能把这次配置文件变化直接理解为“作者换了实际请求设备，修复批量接口”。

这不等于整个新版没有业务修改；`hongguo.pyc` 还有本专项之外的变化，应结合主报告的视频模型调用链比较。这里也没有运行 Windows 原程序，不能据静态比较宣称新版在线成功或失败。

## 直接比较结果

| 对象 | 结果 | 证据 |
|---|---|---|
| `app/config.json` | 仅 3 个设备字段的值变化；主机、其余 query、全部 session headers 相同 | JSON 的 `config.changed_fields`、`config.*_unchanged` |
| `app/devices.json` | 字节完全一致，69 条 | JSON 的 `artifacts.app/devices.json`、`device_pool` |
| `app/devicepool.pyc` | 16 字节 pyc 头也相同；仅编译源路径不同 | JSON 的 `modules.app/devicepool.pyc` |
| `app/sign/unidbg-sign.jar` | 字节完全一致 | SHA-256 `bcbfb6fae0952435bddf286457d785c1a3f9ba67c83503cf3f87cb34cedb252b` |
| `libmetasec_ml.so` | 字节完全一致 | SHA-256 `20d3f8dd8d0d47e4e3c0da0f377eaf69e72a72c8d214ca56e6e7493c65a8fc2d` |
| `libc++_shared.so` | 字节完全一致 | SHA-256 `e8373ee43274541efd2d34fe0588d55bf953612e1417ad47cfd2c4bd1aa383d0` |
| `ms_16777218.bin` | 字节完全一致 | SHA-256 `c44b4f1e213490e3518f85fa8dace1e7d52b77d3d360ef06cc27b6562adfb62c` |
| Java `cacerts` / `blocked.certs`，Python / pip `certifi/cacert.pem` | 安装器嵌入清单的 SHA-256 均相同 | JSON 的对应 `artifacts` 项；本专项没有独立提取这 4 项复算 |
| `app/nettls.pyc`、`app.pyc`、`launcher.pyc` | 排除编译路径后，完整递归代码对象相同 | JSON 的 `modules.*.normalized_module_equal` |

设备池的 device ID 长度分布为：13 位 1 条、14 位 4 条、15 位 11 条、16 位 53 条。此项只是包内观测，不说明平台实际认可这些 ID，也不说明其来源。

## 为什么 `config.json` 的变化未必影响实际设备

新版 `hongguo.pyc` 模块初始化的源行 88 读取 `config.json`，源行 95 调用 `devicepool.load_pool(CFG['base_query'])`。随后：

1. `devicepool.load_pool`（源行 98）优先读取默认 `app/devices.json`，或 `DEVICE_POOL` 指定的文件。
2. 默认没有 `DEVICE_POOL` 环境变量时，加载随包设备后使用 `session=True`。
3. `DevicePool.__init__`（源行 61）会从设备列表随机选择会话级 `_pin`。`current`（源行 77）在该模式直接返回 `_pin`，不是固定取第 0 条。
4. `hongguo.build_url`（源行 482，字节码偏移 4–168）先复制 `CFG['base_query']`，再用 `_pool.current()['query']` 更新覆盖。69 条记录均含 `device_id`、`iid`、`cdid`，因而均覆盖本次 config 变化的全部三项。
5. 同一个函数再应用业务 `extra`，最后计算新的 `_rticket`。`_req_headers`（源行 494）会使用当前设备的 UA，并在存在设备池时删除 `cookie` 与 `x-tt-token`，再生成请求体 MD5。

新旧 config 的基础 device ID 均不在随包 69 条设备 ID 中。上述覆盖结论依赖“随包设备池正常读取、未被外部配置替换、业务参数未再次覆盖”的条件；当池文件缺失或加载失败时，基础 config 才可能直接影响设备字段。

完整指令序列保存在 JSON 的 `instruction_evidence`，以模块/函数全名索引；其中 `source_line` 是 pyc 保留的原 Python 源行号，`offset` 是函数内字节码偏移，不是当前 Markdown 行号。

## 设备生成、轮换、刷新都沿用旧实现

- `gen_device`（源行 39）：从 8 组手机 profile 中随机选一组；用 `_digits` 生成 device ID / iid，其位数来自模板，模板缺失时默认 16；`cdid` 使用 UUID。组装 UA、机型、Android 版本等字段。它不向平台注册设备。
- `load_pool`（源行 98）：若找不到有效池，只在 `DEVICE_POOL_SIZE > 0` 时调用 `gen_device` 生成并尝试写回 JSON。默认大小为 0，因此不能理解为“每次启动都自动注册/换新设备”。
- `DevicePool.rotate`（源行 86）：在已有列表上推进索引；会话模式更新 `_pin`，另一种模式更新当前线程的设备。它没有发起设备注册或刷新设备身份的 HTTP 请求。
- `hongguo.api`（源行 543）：`RiskControlError` 分支在源行 573 调用 `rotate_device` 并退避；部分请求/解析异常分支在源行 591 同样轮换；认证过期分支在源行 567 调用 `refresh_session`。这些函数及其调用逻辑在新旧版本中相同。
- `refresh_session`（源行 437）：向配置签名服务的首个地址请求 `GET /grab`，读取返回 URL 的 query 和部分会话 headers，更新 `CFG` 并写回 `config.json`；有 20 秒节流。它是旧有兼容路径，新版没有新增它。

随包 JAR 完全相同，因此可以复用旧版 [FqTrace 字节码证据](../../analysis/evidence/FqTrace.javap.txt)：`serveStatic` 在证据第 882–887 行注册 `/sign`，没有注册 `/grab`。不能把 Python 存在 `refresh_session` 当成“随包 JAR 已实现设备刷新”，也不能据此证明 `/grab` 在用户配置的其他签名服务部署上一定不可用。

## 签名调用链没有实质变化

逐函数比较确认以下函数的完整代码对象（仅去除编译路径）相同：

`hongguo.sign`、`_sign_auth_headers`、`_sign_post_once`、`_sign_session`、`_reset_sign_session`、`_next_sign_server`、`_signer_warm`、`signer_reachable`、`_api_once`、`api`、`build_url`、`_req_headers`、`refresh_session`、`rotate_device`；启动器的 `_start_signer`、`_restart_signer`、`_sign_probe_once`、`_signer_watchdog` 及相关本地探测函数也相同。各函数的原源行号、规范化 SHA-256、依赖名见 JSON 的 `functions`。

因此，本包比较没有提供“作者替换了签名计算实现、签名库、签名 HTTP 客户端或设备刷新机制”的证据。若新版解决视频模型问题，应优先核查本专项以外确实变化的视频模型业务代码，而不是仅从 config 文件哈希或 pyc 文件哈希变化推断修复点。

## 比较方法与边界

旧根目录：`/Users/tt/Desktop/rea/analysis/extracted`。新根目录：`/Users/tt/Desktop/rea/research/latest-installer-20261014/extracted`。

pyc 的编译源路径由 `D:\code\Hongguo-App\installer\_stage_172g\...` 变为 `D:\code\Hongguo-App\installer\_stage\...`。递归比较保留 opcode、常量、符号、函数参数布局、flags、行号表、异常表等，仅排除 `co_filename`，pyc 文件头另行记录。故“规范化相同”比只比 opcode 更严格，也不会把编译路径变化误报成业务修复。目标模块始终只解析，不 import 或执行。

此专项没有证明设备池最初是如何获得的，没有查询作者服务器，也没有证明批量接口 110001 的平台内部判定。`analysis`、`HongguoCLI`、`HongguoDesktop` 和输入安装器均未修改；新写入的文件仅为本报告及同目录的证据 JSON。
