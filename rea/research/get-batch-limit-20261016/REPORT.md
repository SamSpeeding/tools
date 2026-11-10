# 新 GET 批量接口：每次 VID 数量边界实测

**本次实测可以一次完整返回 15 个 VID；16 个和 20 个均返回 `100103 / PARAM_INVALID`。原程序中的 5 是客户端主动分组限制，并非这次线上观察到的服务端边界。** 单剧和跨剧两组 15/16 对照结果一致；结论适用于本次固定设备、签名、App 参数和接口，不是对所有客户端或未来服务行为的永久承诺。[逐次结果](./results.json)、[独立复核](./verification.json)

实验时间：2026-10-16 17:40:40–17:44:09，Asia/Shanghai，共 209 秒。15 次真实模型请求，涉及 2 部剧、40 个不同 VID；11 次完整成功，共 117 个模型、585 条清晰度轨道；4 次参数错误。未下载媒体，没有修改项目实现。[汇总](./summary.json)

## 原程序的 5 是怎样产生的

1.0.0.76 包内原字节码将 `_VM_BATCH_N` 设为 `5`；`_vm_lookup` 把传入大小限制为 `max(1, min(int(batch_size or _VM_BATCH_N), _VM_BATCH_N))`；`_vm_tab_pass` 再按该大小切片发送 GET。它能证明原客户端每组最多 5，不能单独证明服务端最多 5。[原字节码常量](../latest-installer-20261016/evidence/model-functions.txt#L1270)、[分组大小处理](../latest-installer-20261016/evidence/model-functions.txt#L640)、[切片发送](../latest-installer-20261016/evidence/model-functions.txt#L513)

## 固定条件和实际请求

请求入口为 `GET https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/`。除原项目的设备/App 公共 query 外，固定参数为 `video_platform=1024`、`need_all_video_definition=true`、`device_level=3`、`detail_page_version=0`，`video_id` 是逗号连接的本批 VID；GET 无 body、无 `x-ss-stub`。[实验代码](./probe.py)、[复用的请求实现](./probe_support.py)

全程使用 `HongguoDesktop/config/devices.json[0]` 的同一设备 ID、安装 ID 和 CDID，以及现有 App 配置、`curl_cffi` Chrome 传输方式。签名为现有 JAR 的其他头加现有本地 Python Helios/Medusa v3，每次重新签名；没有切换 host、注册或轮换设备。7 个阶段各自启动并关闭本地签名进程，因此这次是固定设备测试，并非同一个签名进程长时间连续运行。[阶段记录](./results.json)、[独立身份核验](./verification.json)

本轮绕过原客户端的 5 条分组，每个表内数量确实只发送一条 GET。每批 VID 均不重复，来自已有的 74 集与 28 集目录；请求间隔至少 3 秒，没有重试、回退或模型缓存。原计划按阶梯增加，遇到失败后收缩范围，40/74/100 条没有发送，也没有把计划数量当作测试结果。[目录来源与哈希](./catalog.json)、[实际执行代码](./probe.py)、[全部原始请求的独立核验](./verification.json)

## 结果

| 阶段 | 单次 VID 数量 | 完整成功/返回结果 |
|---|---|---|
| 阶梯 | 5、6、10、20 | 5/5、6/6、10/10；20 返回参数错误 |
| 反序复核 | 11、10、20 | 11/11、10/10；20 再次参数错误 |
| 缩小范围 | 15、13、12 | 15/15、13/13、12/12 |
| 上邻边界 | 16 | 参数错误 |
| 跨剧、反序 | 15、16 | 15/15；16 参数错误 |
| 原 20 条的后 10 条 | 10 | 10/10 |
| 跨剧失败组末段 VID 对照 | 10 | 10/10 |

来源：[ladder](./ladder.json)、[boundary](./boundary.json)、[narrow](./narrow.json)、[upper](./upper.json)、[cross](./cross.json)、[tail](./tail.json)、[cross-tail](./cross-tail.json)。

**15 条两次完整成功；16 条两次失败；20 条两次失败。** 四次失败的真实业务响应均为：

```json
{"code":100103,"message":"PARAM_INVALID","data":null}
```

全部 15 次 HTTP 状态都是 200，因此不能用 HTTP 200 判定成功。成功响应顶层均为 `code=0 / SUCCESS`，`data.video_model_data` 的键集合与实际请求 VID 集合完全一致；每个模型均可解析，并有 360p、480p、540p、720p、1080p 五档、非空 HTTP(S) 主备地址和正视频时长。[逐项独立复核](./verification.json)

独立复核直接读取了全部 15 份原始请求/响应，确认 URL 中的数量、顺序、唯一性与摘要一致，没有暗中拆成每组 5。四次失败请求涉及的每个 VID 都在较小批次中成功返回，排除了其中某集本身无效这一解释。相同请求 VID 在不同成功批次中映射到同一个内部媒体 ID，不同请求 VID 的内部媒体 ID 也不同。模型内部的 `video_id` 是 32 位媒体标识，与请求的 19 位数字 VID 不是同一种标识，未错误地要求二者相等。[独立复核记录及原始文件哈希](./verification.json)

## 结论范围与文件保护

目前可以把 **15 看作本次请求条件下已验证的最大完整批量，并把 15/16 看作本次观测到的边界**。这比原程序主动选择的 5 更大。没有验证 14、17–19 或所有可能参数组合，也没有平台官方上限文档；不能由有限样本证明全局、永久硬限制，或推断后台究竟按 VID 数量还是参数长度校验。此次没有媒体下载、解密、播放验证，也不是长期稳定性测试。[原始分阶段结果](./results.json)

354 个纳入保护清单的项目、配置与逆向文件前后哈希一致；这包括生产 Desktop/CLI/PHP 和 analysis 的已纳入文件，排除运行依赖、构建产物、输出、实验目录等，不能扩大为整块磁盘没有变化。7 次签名进程均已退出，复制的运行依赖已删除。本轮材料全部保存在本研究目录。[汇总与保护检查](./summary.json)、[独立阶段核验](./verification.json)

`private/` 保存完整请求和响应，目录权限 0700、15 个原始记录文件权限 0600，含设备信息、签名和临时媒体地址；本报告与复核摘要不复制这些敏感值。`verification.json` 记录逐份原始文件 SHA256 和独立判定，便于后续复核。
