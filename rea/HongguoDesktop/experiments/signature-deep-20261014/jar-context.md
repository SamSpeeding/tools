# 原 JAR 签名上下文：静态数据流核对

日期：2026-10-14。范围：读取原 JAR、保留的 `javap` 证据、当前签名启动器和 Python 参考脚本。未运行目标 JAR，未请求网络，未修改应用或冻结的 `analysis/`。仅新增本报告及 [`jar-context-evidence.json`](jar-context-evidence.json)。

## 结论

当前应用启动的是 **`FqTrace serve`**。它将完整 URL 和请求头文本直接交给 SO；Java 层既没有把 URL 中的设备/安装 ID 拆出并设置到 SDK 的步骤，也没有调用 `MetasecSign.driveInit`。因此不能因为 JAR 内存在 `init_config.json` 字符串，就认定当前签名器已读取它初始化设备。

可以静态确认的差异是：Python 参考实现显式填充 Helios/Medusa 的 aid、license、SDK 版本、设备 ID 和环境字段；原 JAR 的活跃 Java 包装层主要提供 URL/headers，加上固定模拟包名、版本号等 JNI 回调。**这只能证明输入路径不同，不能单靠 Java 字节码推断 SO 最终输出了哪个 aid/license、哪些回调实际被调用，或是哪一项引发服务端拒绝。** 这些问题应与主任务的签名解码和线上实验证据合并判断。

## 证据身份和真实入口

原 JAR：`HongguoDesktop/vendor/sign/unidbg-sign.jar`，SHA-256 `bcbfb6fae0952435bddf286457d785c1a3f9ba67c83503cf3f87cb34cedb252b`。

这次使用 `/opt/homebrew/opt/openjdk/bin/javap -p -c` 对原 JAR 重新只读反汇编，`FqTrace`、`MetasecSign` 两份输出与 `analysis/evidence/` 保留文本逐字节一致。`javap` 只读类文件，不初始化目标类。系统 `/usr/bin/javap` 未找到运行时，随后使用已安装的 Homebrew JDK 完成核对。

| 证据 | 位置 | 观察 |
|---|---|---|
| JC01 | [hongguo_signer.py:54](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_signer.py:54) | 命令明确指定 `-cp unidbg-sign.jar com.hongguo.sign.FqTrace serve <port>` |
| JC01 | [FqTrace.javap.txt:949](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:949)，`main` 偏移 0–47 | `serve` 分支启动服务后等待，不执行后面的样例 URL |
| 身份核对 | JAR `META-INF/MANIFEST.MF` | Main-Class 为 `MetasecSign`，但显式 `-cp ... FqTrace` 启动不会使用它 |

`FqTrace.main` 偏移 130 的 `aid=1967` 样例 URL 只存在于无参数调试分支，不能当作生产请求或签名内 aid。相同道理，`MetasecSign.main` 的示例 aid=8662 也不能证明活跃 FqTrace 的配置。

## 活跃 FqTrace：从请求到 native 的路径

1. 应用先序列化请求体，计算 MD5 放入 `x-ss-stub`。发给本地签名器的 JSON 只有 `url` 和 `headers`，不单独发送原请求体。[hongguo_api.py:191](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:191)、[hongguo_api.py:237](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:237)（JC11）。
2. HTTP handler 从 JSON 取出 URL 字符串；把 header 名和值按 `name\r\nvalue` 拼接，条目之间加 `\r\n`。只把 URL、这段文本以及结果 future 入队。[FqTrace.javap.txt:1081](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:1081)，`lambda$serveStatic$2` 偏移 70–258（JC03）。
3. 单独工作线程先创建一个 FqTrace，持续复用它处理队列；每次只调用 `signMap(url, headerText)`。[FqTrace.javap.txt:1201](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:1201)，`lambda$serveStatic$1` 偏移 0–72（JC03）。
4. `signMap` 不修改两参，交给 `sign`；`sign` 对 SO **offset `0x168c80`（1477760）** 调用 `Module.callFunction(emulator, offset, [url, headerText])`。没有第三个设备/配置参数。[FqTrace.javap.txt:240](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:240)，`sign` 偏移 0–63（JC04）。
5. 返回 C 字符串后，`signMap` 仅按换行拆成 `X-` 名称/值配对放入 map；不修正输出的 aid/license/设备字段。[FqTrace.javap.txt:786](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:786)，`signMap` 偏移 0–90（JC04）。

完整读取这些方法后，未发现 Java URL 参数解析、设备/iid setter 或 Config 组装。**完整 URL 已经送入 SO，所以仍可能由 SO 自行解析；“Java 没有同步”不等于“SO 完全不读 URL”。** 这是有边界的否定证据（JC05），没有跨越到 native 内部。

## constructor 与 JNI 回调提供了哪些上下文

构造函数在 [FqTrace.javap.txt:29](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:29)，偏移 0–410（JC02）：

| 项目 | 确定值/来源 | 字节码偏移 |
|---|---|---|
| 模拟进程名 | `com.dragon.read.oversea.gp` 固定 | 45–47 |
| data/files inode | 固定 `655781` / `655864` | 97–132 |
| uid | 固定 `10074` | 137–149 |
| Android resolver API | 固定 23 | 167–184 |
| native 库 | `../capture/fq_oversea/libmetasec_ml.so` | 9–14、355–377 |
| JNI 初始化 | 调用 `DalvikModule.callJNI_OnLoad` | 380–386 |
| 设备/安装 ID、aid/license 初始化 | 此 constructor 未设置，也未读取 config.json | 0–410 的完整方法 |

`callStaticObjectMethodV` 对 `com/bytedance/mobsec/metasec/ml/MS->b(` 的调用仅读取第 0 个 int 参数传给 `handleMS`，没有读取该 callback 的其它参数。[FqTrace.javap.txt:516](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:516)，偏移 0–21（JC06）。

`handleMS` 的完整七分支位于 [FqTrace.javap.txt:446](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:446)（JC06）：

| op | 返回内容 | handleMS 偏移 |
|---|---|---|
| `0x10003` | 固定 `/data/user/0/com.dragon.read.oversea.gp/files/.msdata` | 68–79 |
| `0x2000001`、`0x2000002` | `true` | 80–85 |
| `0x1000010` | 固定整数 `68132` | 86–106 |
| `0x1000011` | 固定字符串 `6.8.1.32` | 107–118 |
| `0x1000002` | 存在时读取 `ms_16777218.bin` 原始 bytes，否则 null | 119–153 |
| `0x1000000e` | `System.currentTimeMillis()` | 154–174 |
| 其它 | null | 175–176 |

这里没有 `device_id`、`iid`、aid/license 的独立回调实现。未命中的 JNI 调用仍可落入父类 AbstractJni；本次没有全面研究 unidbg 默认行为。另需注意：**定义回调并不证明本轮实际签名执行调用了这个分支。**

FqTrace 的 IO resolver 只明确映射 `libmetasec_ml.so`，没有 `MetasecSign` 那种 `.msdata`→本地目录映射。[FqTrace.javap.txt:768](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:768)，偏移 0–28。不能据固定 `.msdata` 路径进一步推断已有设备持久化内容。

## 同 JAR 中另一套 MetasecSign，不要与当前路径混淆

- 构造函数固定包名 `com.phoenix.read`、uid=10174；JNI version 回调固定 72532 / `7.2.5.32`。[MetasecSign.javap.txt:31](/Users/tt/Desktop/rea/analysis/evidence/MetasecSign.javap.txt:31)、[MetasecSign.javap.txt:458](/Users/tt/Desktop/rea/analysis/evidence/MetasecSign.javap.txt:458)（JC08）。
- 若 `noinit` 系统属性不存在，constructor 偏移 414–415 调用 `driveInit`。[MetasecSign.javap.txt:207](/Users/tt/Desktop/rea/analysis/evidence/MetasecSign.javap.txt:207)（JC07）。
- `driveInit` 读取 `../capture/cronet/init_config.json`，UTF-8 trim 后作为不透明字符串传给 `ms/bd/c/m.a(IIJLjava/lang/String;Ljava/lang/Object;)`，五参是 **`[0x4000001, 0, 0L, configText, null]`**。Java 没有解码其中 aid/license/设备内容；文件缺失直接返回。[MetasecSign.javap.txt:271](/Users/tt/Desktop/rea/analysis/evidence/MetasecSign.javap.txt:271)，偏移 0–154（JC07）。
- 其 `sign` 调用的是另一个 SO offset `0x27d288`，传六参 `[url, headers, 24, tick, 0x00ffffffffffffff, counter]`，每次 tick+=1048576、counter+=1；这些也不属于当前 FqTrace。[MetasecSign.javap.txt:386](/Users/tt/Desktop/rea/analysis/evidence/MetasecSign.javap.txt:386)（JC08）。
- 自有 `com/hongguo/sign/` archive 成员仅 EncryptRun、FqTrace、FqTrace$1、MetasecSign 四个 class；没有自有 Config class。JAR 没有 init/config JSON 成员。此 inventory 不涵盖 SO 内部 Config，也不否定外部文件的可能性（JC12）。

## Python 参考脚本明确带入的字段

| 项目 | Python 实现 | 原 FqTrace Java 层 |
|---|---|---|
| Helios aid/license | 明文构造 `{khronos}-1588093228-8662`，key seed 也用固定 `8662` | 没有 Java 级构造；返回来自 SO |
| Medusa aid/license | `ms_app_id="8662"`，`license_id="1588093228"` | 无独立设置，native 结果需解码确认 |
| SDK | `v04.06.04-ml-android`、`67503104` (`0x04060400`) | Java 没有对应字段赋值 |
| 设备 ID | devices 优先，URL 的 device_id/did 后备；填入顶层 field 5 和嵌套 device | 全 URL 传 SO；无 Java 提取/setter |
| 安装 ID / iid | 编码 schema 没有单独 iid 字段；完整 query hash 仍包含 URL 中的 iid | 全 URL 传 SO；无 Java 提取/setter |
| App version | devices.version_name → URL.version_name → 默认 `7.1.3.32`；顶层和 env 都填入 | JNI 回调能提供固定 `6.8.1.32`，是否被调用待验证 |
| 型号/品牌/系统 | devices 或 URL 提取，显式填入环境 | JNI 未单独实现；仍可能被 native 由 URL 或其它路径获取 |
| 环境 | PID/launch time 每次随机；一批硬编码采样值、部分当前时间 | 模拟器 + native 状态；具体字段未静态解码 |

Python 证据：[红果短剧.py:3165](/Users/tt/Downloads/红果短剧.py:3165)（Helios）、[红果短剧.py:3196](/Users/tt/Downloads/红果短剧.py:3196)（Medusa 上下文）、[红果短剧.py:3084](/Users/tt/Downloads/红果短剧.py:3084)（schema）、[红果短剧.py:3298](/Users/tt/Downloads/红果短剧.py:3298)（两者的组合调用）（JC09–JC10）。这不是官方字段语义声明，仅描述该参考实现的实际源码。

## 对主实验解码候选常量的定点查询

主任务报告候选 Helios 明文中的 JAR aid/license 为 `3019` / `1611921764`；本分支将其作为检索目标，**该解码结论应引用主任务单独的回环验证证据**。这里没有通过静态字符串反向证明它。

- 在活跃 SO、自有 class、证书原始 bytes 中，未找到这两个十进制 ASCII 常量。没有进一步展开全 SO 数据流或混淆解码。
- Python 的 `config_key` / `config_iv` / `sign_key` 原始 byte 串在活跃 SO 和证书中没有匹配；不能由此推出 SO 没有等价密钥，因为它可能被编码、派生或动态构建。
- 32-bit little-endian 的 3019/8662 在 SO 中存在不对齐 byte 命中，无 xref 或执行数据流支持，不能当作 config 来源。
- `ms_16777218.bin` 是 2014-byte ASCII hex，对应 1007-byte DER。离线解析为 subject/issuer 同为 `C=CN, ST=GuangDong, L=DongGuan, O=Oplus, OU=OSTeam, CN=AndroidTeam` 的 X.509 证书；DER SHA-256 为 `fc98dae63ad39626c8c67fbe83f2f06f74932a9cd146b92cecfc6a047a904386`。FqTrace 实际回调交出去的是文件原始 ASCII bytes。本次没有证据证明该证书生成或选择了某个 license（JC13）。

因此，当前 Java 层可排除“已有一段显式把 URL 的 aid/license/device 同步进 SDK 的代码被我们遗漏”的说法；**native 内部的默认值、派生值与初始化状态仍未确定。**

## 可与主任务实验交叉验证的点

1. 对相同 URL/body 的两套 Helios 解码回环，确认 aid/license 差异；不要从看起来不同的 Base64 直接判断算法错误。
2. 对 Medusa 使用能通过回环的解析方案，再比较嵌套设备、app/SDK、query/body/time 绑定字段，区分“格式/密钥不同”和“环境字段不同”。
3. 原设备、多集、多 VID 的批量成功证据可以证明替换组合在样本下可用，但不单独证明只改某一个 aid/license 即可长期稳定。
4. 若以后需要验证 native 上下文同步，应在隔离副本中逐项记录或对照；当前静态结论不构成直接改应用代码的依据。

本分支仍未知：SO 实际怎样得到签名内 aid/license、是否解析 URL 填入其他环境、回调版本是否真正参与当前输出、JAR Medusa 的明文及密钥差异、服务端具体验证规则。
