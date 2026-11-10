# 批量模型接口：固定 JSON、客户端差异与设备生命周期静态研究

日期：2026-10-14（Asia/Shanghai）。截至本报告完成，工作范围仍仅为只读本地源码与主任务已留存的实验记录，本研究没有发起新的网络请求，不修改应用、配置、vendor、原 CLI 或冻结的 `analysis/`。新一轮在线实验由主任务单独记录，不能把下面的候选因素写成已经证实的服务端规则。

## 结论

**JSON 作为存储形式没有特殊问题；需要区分固定的协议档案、持久的设备身份、会过期的会话，以及每次重算的请求字段。** 当前应用并不是把整份历史请求 JSON 原封不动发送：设备档案覆盖基础 query，`_rticket`、请求体 MD5 和签名都按本次请求重新生成。但设备来源、注册状态、何时失效及如何取得新的有效会话并没有完整复原；把安装包中的设备列表永久作为唯一身份来源，是明确的生命周期局限，尚不是 `110001` 的根因证明。[应用构造 URL 与 headers](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:181)、[每次调用签名器](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:237)、[worker 固定使用设备第 0 组](/Users/tt/Desktop/rea/HongguoDesktop/backend/worker.py:40)。

**第三方脚本与应用不是“相同请求，只有签名实现不同”。** 两者的包与版本档案、硬件与语言、渠道、query 字段和编码、headers、类型键、签名家族、HTTP 客户端，以及 ID 长度/生命周期均不同。脚本出现过“新 device_id 首次成功，重复失败”，只证明其请求组合在那一轮测试中与设备 ID 有明显关联，不能证明固定 JSON 导致应用失败，更不能证明脚本已经解决了稳定设备生命周期。[脚本请求构造](/Users/tt/Downloads/红果短剧.py:3326)、[第三方设备因素既有实验](/Users/tt/Downloads/红果短剧研究-20261013-nl6qxoj5/device-factor-results.json:1)、[应用只改 device_id 的既有实验](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/batch-device-id-comparison.json:1)。

## 配置字段该按什么生命周期理解

这里的“应持久”是合理的客户端建模建议，不冒充已经核实的平台期限或注册契约。

| 类别 | 当前字段/材料 | 当前代码行为 | 研究判断 |
| --- | --- | --- | --- |
| API 与应用协议档案 | `api_host`、`aid`、`app_name`、`channel`、`version_name`、各 version code、UA/SDK 版本 | 从 JSON 读取，后续请求复用 | 可以固定保存，但各项应形成一套一致档案；平台协议升级时可能需要整组验证。固定不代表永远有效。 |
| 设备身份 | `device_id`、`iid`、`cdid` | worker 读 `devices.json[0]`；覆盖 `base_query` 同名字段 | 身份应该有来源并保持关联；不能把任意随机数等同于平台注册 ID，也没有证据表明每次请求必须换 ID。 |
| 设备环境档案 | 品牌、型号、系统/API、ROM、屏幕、DPI、ABI、语言及 UA | 基础 JSON 提供；当前 69 个设备条目只覆盖身份三字段和 UA | 应与身份来源/签名环境一起理解。单改 ID 不能验证环境一致性。 |
| 业务选项 | `biz_param`、类型键、vid | 代码按功能构造 | 本来就是固定协议参数加具体请求目标；不需要自动刷新。类型键含义不能仅靠两个脚本的取值推定。 |
| 登录/安全会话 | Cookie、`x-tt-token`；脚本可接收安全 token 字段 | 应用当前配置没有 Cookie/`x-tt-token`，且传入 device 时主动删除；脚本一般传入两个 ID，安全 token 默认为空 | 若将来取得真实会话，应单独持久化和处理有效期。当前错误不能简单称为“JSON 中 Cookie 过期”。 |
| 请求时间 | 应用 `_rticket`；脚本 `ts`、`_rticket`、`x-ss-req-ticket`、`x-khronos` | 都在调用时取得时钟值，脚本多次分别取时 | 逐请求生成。代码不是重放旧请求时间。是否需要这些字段组合是可控实验问题。 |
| 请求完整性与签名 | `x-ss-stub`、签名 headers | 两者都按当前 body 计算 MD5，并按当前 URL/headers/body 相关内容签名 | 不应从 JSON 保存后直接复用旧签名。应用目前确实重新调用签名器。 |
| 签名运行环境 | 应用 JAR/SO/证书样本；脚本内环境字段及随机值 | 应用 worker 生命周期复用本地签名器；脚本每次在 Python 中重新构造签名环境 | 这是独立于 JSON 的另一个状态层，不能用换一个 query ID 就证明它已完全同步。 |

字段来源：[应用 config](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:2)、[设备条目](/Users/tt/Desktop/rea/HongguoDesktop/config/devices.json:2)、[应用覆盖/动态字段](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:181)、[业务 body](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:379)、[脚本 device 配置](/Users/tt/Downloads/红果短剧.py:3326)、[脚本动态签名](/Users/tt/Downloads/红果短剧.py:3298)。

当前文件的静态盘点：`devices.json` 有 69 组，每组 query 都只有 `device_id/iid/cdid`。did 位数分布为 16 位 53 组、15 位 11 组、14 位 4 组、13 位 1 组；第 0 组为 16 位。第三方 `Spider.__init__()` 则生成两个 18 位随机数。因此昨日应用“新 B/C”的同位数随机 ID 测试，并没有覆盖第三方的 18 位取值范围。[生成诊断 ID 的代码](/Users/tt/Desktop/rea/HongguoDesktop/scripts/probe_batch_device_id.py:30)、[Spider 构造](/Users/tt/Downloads/红果短剧.py:3733)。这只是待控制的变量，不能推断 18 位就有效。

## 两份客户端的精确请求差异

| 因素 | HongguoDesktop | `红果短剧.py` | 源码位置 |
| --- | --- | --- | --- |
| 模型路径 | 优先 `/novel/player/multi_video_model/v1/`，失败回退 `/novel/player/video_model/v1/` | 直接调用批量路径，没有该处单视频回退 | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:393)、[脚本](/Users/tt/Downloads/红果短剧.py:534) |
| 主 host | `api5-normal-sinfonlinec.fqnovel.com` | `api5-normal-sinfonlineb.fqnovel.com` | [配置](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:2)、[脚本](/Users/tt/Downloads/红果短剧.py:534) |
| App 档案 | UA 包名 `com.phoenix.read.oversea.gp`，7.2.9.32/72932，`googleplay` | UA 包名 `com.phoenix.read`，7.1.3.32/71332，`update_64` | [应用](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:11)、[脚本 UA](/Users/tt/Downloads/红果短剧.py:536)、[脚本 query](/Users/tt/Downloads/红果短剧.py:3341) |
| 共同 App 标记 | `aid=8662`、`app_name=novelread` | 相同 | 同上 |
| 硬件/语言 | Samsung SM-S938U、Android 15/API35、1080×1920、480dpi、en/UA en_US | Redmi 25053RT47C、Android16/API36、1280×2772、520dpi、zh/UA zh_CN | [应用](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:7)、[脚本](/Users/tt/Downloads/红果短剧.py:3333) |
| 身份 | 已保存的第 0 组 did/iid/cdid | 每个 Spider 实例随机 did/install_id，URL 中 install_id 叫 `iid`；没有 cdid | [worker](/Users/tt/Desktop/rea/HongguoDesktop/backend/worker.py:40)、[脚本](/Users/tt/Downloads/红果短剧.py:3733)、[URL](/Users/tt/Downloads/红果短剧.py:3343) |
| query 特有字段 | 包括 `cdid`、`rom_version`；只额外生成 `_rticket` | 没有这两项；额外生成 `ts`、`_rticket` | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:181)、[脚本](/Users/tt/Downloads/红果短剧.py:3116) |
| query 编码 | `quote(..., safe='')`，`*` 编为 `%2A`，保留 dict 插入顺序 | `urlencode(...).replace('+','%20').replace('%2A','*')`，`*` 保留 | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:188)、[脚本](/Users/tt/Downloads/红果短剧.py:3113) |
| 类型键 | `mixed_video_id_map:{"1":[vid]}` | `mixed_video_id_map:{"1004":[vid]}` | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:400)、[脚本](/Users/tt/Downloads/红果短剧.py:3383) |
| biz_param | 额外有 `disable_video_relate_book:false` | 不传这个字段；其他所列业务参数相同 | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:382)、[脚本](/Users/tt/Downloads/红果短剧.py:3372) |
| 额外 headers | `passport-sdk-version=5051452`、`x-tt-store-region=kh`、`x-tt-store-region-src=uid` | `passport-sdk-version=50561`、Accept、`x-xs-from-web`、动态 `x-ss-req-ticket`、`x-tt-request-tag`、`x-vc-bdturing-sdk-version=3.7.2.cn`、空 `x-tt-dt` | [应用配置](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:34)、[脚本](/Users/tt/Downloads/红果短剧.py:3385)、[x-tt-dt](/Users/tt/Downloads/红果短剧.py:3323) |
| Content-Type | `application/json; charset=utf-8` | `application/json; charset=UTF-8` | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:198)、[脚本](/Users/tt/Downloads/红果短剧.py:3388) |
| 序列化/MD5 | compact UTF-8 JSON，MD5 大写 | compact UTF-8 JSON，MD5 大写 | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:240)、[脚本](/Users/tt/Downloads/红果短剧.py:3100) |
| 签名协议输出 | 包括常见六项 argus/gorgon/helios/khronos/ladon/medusa，另有 `x-neptune`、`x-soter`；该样本长度分别为 argus 240、ladon 48、medusa 880、neptune 12、soter 120 | 包括常见六项，没有 neptune/soter；argus/ladon 只是时间戳 Base64 占位值，各 8 字符，medusa 944 字符（该样本） | 本次只读核对的原始 `request.headers` 见下方勘误；[脚本实现](/Users/tt/Downloads/红果短剧.py:3304) |
| HTTP 传输 | `curl_cffi.requests.Session(impersonate="chrome")`，禁用重定向 | `requests.post()`，该调用未设置禁用重定向 | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:169)、[应用请求](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:210)、[脚本](/Users/tt/Downloads/红果短剧.py:3405) |
| 错误观察 | 检查顶层小写、大写 Code 和 BaseResp，保存回退原因 | `_video_model` 主要找 data 内模型；无模型会抛“video_model 为空” | [应用](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_api.py:257)、[脚本](/Users/tt/Downloads/红果短剧.py:3412) |

表中 HTTP 客户端差异意味着 TLS/默认 headers/连接状态也可能不同；没有抓到最终 wire 请求的字段，不应仅根据显式 headers 字典假定完全一致。既有 HTTP1/HTTP2 对照只证明那两个受测请求均失败，不等于已经覆盖 Python requests 与 curl_cffi 的全部差异。[既有传输实验](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/request-comparison.json:1)。

**签名头数量勘误：** 旧 `request-comparison.json` 只列四项，不能据此断言原签名器只输出四项。另一个旧实验的采集代码明确只挑这四个 key 记录；FqTrace 的 signMap 则泛化接收返回字符串中全部以 `X-` 开头的 header，没有四项白名单。今天第一版 public 摘要又仅白名单记录了常见六项，也不能视为完整头列表。本次只读核对原始 `private/01-baseline-our_original_batch.json` 的 `request.headers` 后确认 JAR **除常见六项，还有 `x-neptune` 和 `x-soter`**；相应 `private/01-baseline-script_A_first.json` 没有这两项。只读取、报告 key 和长度，没有在本文复制签名值。当前 config 的 session_headers 只有五个基础字段，**没有旧 helios/medusa 等签名残留**。完整发送记录应优先于有字段筛选的摘要。[原始应用记录](/Users/tt/Desktop/rea/HongguoDesktop/experiments/batch-model-20261014/private/01-baseline-our_original_batch.json)、[原始脚本记录](/Users/tt/Desktop/rea/HongguoDesktop/experiments/batch-model-20261014/private/01-baseline-script_A_first.json)、[旧采集范围](/Users/tt/Desktop/rea/HongguoDesktop/scripts/probe_original_models.py:177)、[原 signMap](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:786)、[当前配置](/Users/tt/Desktop/rea/HongguoDesktop/config/config.json:34)。

## 第三方脚本有没有“新实例同时刷新了隐藏签名会话”

从源码可确认，`Spider.__init__()` 仅给 `self.device_id` 与 `self.install_id` 赋值，没有建立持久签名对象、计数器或真实注册会话；后续 localProxy 会把这些 ID 或入口参数传给 `_video_model`。媒体缓存是模块级状态，缓存命中可以直接返回视频、不请求模型，故研究模型成功率应直接调用模型函数并记录原始 HTTP 响应，不能把“播放成功”自动算成“批量接口成功”。[构造函数](/Users/tt/Downloads/红果短剧.py:3733)、[localProxy 参数](/Users/tt/Downloads/红果短剧.py:4064)、[先命中缓存再取模型](/Users/tt/Downloads/红果短剧.py:4085)。

脚本的签名每次都会生成新的随机数：Gorgon 种子、Helios 随机数、Medusa proto_rand/hash_rand/xm_rand，以及被放进签名环境的 launch_time 和 process_id。也就是说，重复使用同一个 Spider，并不等于重复使用完全相同的签名环境。脚本没有跨调用保持 PID/launch_time 作为一致会话，而是每次随机；这是一处可观察到的实现特征，不证明服务端要求哪种值。[Gorgon/core](/Users/tt/Downloads/红果短剧.py:3298)、[Helios](/Users/tt/Downloads/红果短剧.py:3165)、[Medusa 环境](/Users/tt/Downloads/红果短剧.py:3209)、[Medusa 外层随机值](/Users/tt/Downloads/红果短剧.py:3277)。

部分环境是固定样本而非真实采集：Medusa `report_ts=1728388016635`，并被重复用于 ts/ts2/ts3，ts4=report_ts+2；硬件容量、内存、亮度、电量等也固定。`report_time`、khronos 又是当前时间。源码注释称其为固定环境采样值，但这不是官方协议证明，不能推断这些值应永远固定或一定应更新。[固定环境与当前时间并存](/Users/tt/Downloads/红果短剧.py:3212)。

在默认 `_video_model` 路径内，did 和设备/版本来自同一 `devices` 字典：它覆盖 URL 中已有同名字段，Medusa 也优先取这个字典；因此暂未发现默认路径中“URL 是新 did，而 Medusa 仍签旧 did”的源码错误。iid 进入 URL 和 query 哈希，但该函数的 Medusa顶层身份明确使用 did。不能脱离这条字段传递链，仅改 URL 再复用旧签名来做 ID 对照。[URL 覆盖](/Users/tt/Downloads/红果短剧.py:3116)、[Medusa 读取](/Users/tt/Downloads/红果短剧.py:3196)。

脚本还存在两个值得明确的边界：`_device_config()` 没有把 config 的 cookie 带入返回字典，因此 `_video_model` 中 `devices.get("cookie")` 分支在这个构造路径下不会生效；x_tt_dt 和两个安全 token 虽支持输入，但 Spider 的常规 cfg 只含两种 ID，它们默认是空。[设备字段](/Users/tt/Downloads/红果短剧.py:3326)、[cookie 分支](/Users/tt/Downloads/红果短剧.py:3396)、[默认 cfg](/Users/tt/Downloads/红果短剧.py:4064)。

## 原签名器也有独立于 JSON 的固定环境

应用每个 worker 生命周期复用一个 LocalSigner，后者执行原包 `com.hongguo.sign.FqTrace serve`，每次把 URL 和 headers 交给它，并非每次重新启动整个签名环境。[worker 懒启动/复用](/Users/tt/Desktop/rea/HongguoDesktop/backend/worker.py:44)、[命令](/Users/tt/Desktop/rea/HongguoDesktop/backend/hongguo_signer.py:54)。

冻结的原 JAR 反汇编显示 FqTrace 建模拟器时写死进程名 `com.dragon.read.oversea.gp`；handleMS 的分支返回 68132/6.8.1.32，而当前外层 query 和 UA 是 72932/7.2.9.32 与 `com.phoenix.read.oversea.gp`。工作线程只创建一次 FqTrace，再循环处理签名任务。这能确认“外层 JSON”和“SO 被告知的模拟环境”不是同一个配置来源；不能仅据此证明签名无效，因为相同签名器的单视频接口已经成功，且尚未动态确认这些 handleMS 分支在每种请求中如何被消费。[模拟包名](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:45)、[固定版本](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:446)、[实例复用](/Users/tt/Desktop/rea/analysis/evidence/FqTrace.javap.txt:1201)、[单视频实测](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/model-contract-probe-device-0.json:1)。

## 固定 JSON 与原包生命周期的关系

原 `devicepool.gen_device()` 自己随机生成 did/iid/UUID 和设备档案；这段函数不是平台注册。`load_pool()` 先读现有 devices.json，只有特定环境开关满足才生成并保存新池。因此原包也不是“每次启动都从平台获取新的有效注册设备”。现有安装包中每个已保存 ID 最初从哪里来，不能由这个生成函数反推。[生成函数](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/device-lifecycle-bytecode.txt:181)、[读取/生成池](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/device-lifecycle-bytecode.txt:559)。

原 `refresh_session` 消费 `/grab` 返回的 URL/headers，受控回放已确认它可以更新 did/iid/cdid/版本等字段；这是消费外部抓取结果，不是完整的设备注册实现。设备池启用后又会覆盖基础身份，并移除 Cookie/`x-tt-token`。原大写 `Code:110001` 在原响应检查中没有触发异常。故“把原刷新函数补回来”不能直接视为已验证修复。[离线回放记录](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/device-lifecycle-audit.json:24)、[原 build_url](/Users/tt/Desktop/rea/analysis/evidence/hongguo.dis.txt:5449)、[原 headers](/Users/tt/Desktop/rea/analysis/evidence/hongguo.dis.txt:5570)。

既有候选注册得到过非零成对 device_id/install_id，但同一原请求条件下旧设备与该新注册设备的批量接口都失败。该注册候选不是完整的 aid=8662 官方设备生命周期证明；已取得 IDs 不代表所有安全会话字段都齐全。[候选注册范围与响应](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/registration-probe.json:1)、[成对 ID 批量对照](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/registered-model-probe.json:1)。

## 给在线实验的控制变量建议

1. 先用两种原始请求实现，在同一时段、同一 vid 做基线，记录每次实际 HTTP 状态、业务码、是否含可用模型、响应 log_id。模型函数直接调用，避免单视频回退和媒体缓存把失败遮住。昨日两套 ID 实验使用的 vid 不同，应在本轮统一。[应用旧样本 vid](/Users/tt/Desktop/rea/HongguoDesktop/docs/evidence/batch-device-id-comparison.json:3)、[脚本旧样本 vid](/Users/tt/Downloads/红果短剧研究-20261013-nl6qxoj5/device-factor-results.json:3)。
2. 把“URL+query+普通 headers+body 的请求档案”“签名家族”“HTTP 传输”分开。相同最终 URL/body 每次重新签名；改变 body 后同步重算 stub。先比较成组上下文，再对有信号的组逐项缩减，避免同时换所有参数后归因于设备。
3. 当前最有信息量的分组为：签名实现及内部环境（原 JAR/SO vs 脚本，两者均包括常见六项，JAR 另发 neptune/soter）；App/设备档案；普通 headers；时间参数 ts/req-ticket；body 的 disable_video_relate_book 与类型键；transport。签名头的存在/缺失与内容差异都是待控变量，不能单凭名称推断服务端含义。host 和类型键已有失败证据，不应把重复相同实验当作新结论。
4. ID 因素需分清：已保存原 ID、任意随机 ID、平台候选注册成对 ID，以及 16/18 位取值范围。每次报告“新”到底指什么。不能以“随机出来以前没用过”替代“平台注册有效”。
5. 重复调用是独立维度。脚本“某个新 did 首次成功”会让交叉顺序造成混杂：如果 A 总先测、B 总后测，结果差异不一定来自 A/B 的修改。记录顺序，必要时对调顺序，小样本结论限定为观测，不宣布永久额度/封禁机制。
6. 本轮不要把每次随机换 ID、移植脚本签名或自动注册接入应用。即使实验找到某组合能成功，也应先检查固定身份的重复请求、不同集、间隔后的稳定性及与原功能的关系。此建议只限定实验解释和后续验证，不要求本轮实施新的设备系统。

## 材料校验

本次只读计算 SHA-256，和前一轮证据一致：

| 文件 | SHA-256 |
| --- | --- |
| `/Users/tt/Downloads/红果短剧.py` | `bea893bea56a24cee9eadc4c004bf9637b6c2129d08b22c9500c012431edd6f1` |
| `HongguoDesktop/config/config.json` | `f6304dc2c4633f6182f4e0cd1e198fea3d23c9fb2aaf556b37b8183fdadb68d2` |
| `HongguoDesktop/config/devices.json` | `eb89e95975451ca065346f524bf83d5b708295deb43d43fd9141200961e5c2fd` |

收到主任务的本轮签名头观测后，又只读核对了四个 JAR：Desktop vendor、原 CLI vendor、冻结 `analysis/extracted/app/sign`、release app 内的副本。四者 JAR SHA-256 全部为 `bcbfb6fae0952435bddf286457d785c1a3f9ba67c83503cf3f87cb34cedb252b`，其中 FqTrace.class 全部为 `e5e8f1b366fefd84e3244da05cd0544a0ae5b2577597067b5f51fd2b6f14a7af`。Desktop、CLI、原提取目录的 `libmetasec_ml.so` 均为 `20d3f8dd8d0d47e4e3c0da0f377eaf69e72a72c8d214ca56e6e7493c65a8fc2d`，`libc++_shared.so` 均为 `e8373ee43274541efd2d34fe0588d55bf953612e1417ad47cfd2c4bd1aa383d0`，证书样本均为 `c44b4f1e213490e3518f85fa8dace1e7d52b77d3d360ef06cc27b6562adfb62c`。因此没有证据支持“当前应用偷偷换了另一份 JAR/SO”；字段采集范围不同导致的摘要头数量差异，不构成二进制变更证据。

源码静态分析可以指出一致性风险与可控变量，不能回答服务端为什么返回 `110001`。本记录不声称查明 IP 限制、设备封禁、一次性额度或平台已下线批量接口。
