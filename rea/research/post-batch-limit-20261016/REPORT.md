# 旧 POST 批量接口的 VID 数量上限

**本次固定请求条件下，旧 POST 批量接口每次支持 15 个 VID；16 个和 20 个被服务端明确判为列表数量超限。** 单剧、跨剧的 15 条请求均完整返回，16 条均失败。与本轮新 GET 实测相同，边界在 15/16；旧接口还返回了直接说明数量超限的 `debug_info`。[汇总](./summary.json)、[独立复核](./verification.json)、[GET 对照记录](../get-batch-limit-20261016/REPORT.md)

2026-10-16 17:51:23–17:52:19（Asia/Shanghai），共 56 秒、8 次真实请求、2 部剧、40 个不同 VID。没有修改生产代码或 analysis，也没有下载媒体。[全部结果](./results.json)

| 请求组 | 每次 VID 数量 | 结果 |
|---|---|---|
| 单剧阶梯 | 5、15、16 | 5/5、15/15 完整成功；16 失败 |
| 跨剧、反序 | 15、16、20 | 15/15 完整成功；16、20 失败 |
| 单剧后段有效性对照 | 10 | 10/10 完整成功 |
| 跨剧失败组后段有效性对照 | 10 | 10/10 完整成功 |

来源：[ladder](./ladder.json)、[cross](./cross.json)、[tail](./tail.json)、[cross-tail](./cross-tail.json)。原计划中的 30/50/74/100 未发送；阶梯遇到 16 失败后即改为边界和有效性对照。

三次失败均为 HTTP 200、业务 `code=100001`，`BaseResp.StatusCode=100001`、`StatusMessage="invalid param"`。16 条的响应明确包含：

```json
{"debug_info":"video_id invalid, param: video_id list len over limit:16"}
```

20 条对应 `video_id list len over limit:20`。这次服务端给出的错误是参数列表超限；不是此前旧接口纯 JAR 签名遇到的 `110001`。不能把 HTTP 200 当作业务成功。[原始响应的独立核验与 SHA256](./verification.json)

请求入口固定为 `POST https://api5-normal-sinfonlinec.fqnovel.com/novel/player/multi_video_model/v1/`；body 使用原有九项 `biz_param` 和 `mixed_video_id_map:{"1":[vid,...]}`。设备固定为生产 `devices.json[0]`，App 配置、Chrome 传输方式不变。沿用生产 `_api_once` 的 JAR 其他签名头加本地 Python Helios/Medusa v3，每次重新签名，不额外替换签名实现。[实验代码](./probe.py)、[复用请求实现](./probe_support.py)

每次实际发送一条 POST，批内 VID 无重复，无隐式拆分、重试、回退、缓存、设备轮换或 host 切换；请求间隔至少 3 秒。4 个阶段各自启动并关闭本地签名进程。独立复核直接读取全部 8 份原始请求/响应，确认 body 的真实数量、类型键 `"1"`、VID 顺序与摘要一致，并逐条验证 `x-ss-stub` 等于实际 body 字节的 MD5。[独立复核](./verification.json)

5 次成功共完整返回 55 个模型、275 条清晰度轨道。每次响应 VID 键集合与请求完全相同，每个模型具 360p/480p/540p/720p/1080p 五档有效主备 URL。失败组中的每个 VID 都在较小批次中成功返回，排除了某集本身无效；同 VID 跨批次的内部媒体 ID 保持一致。[模型与有效性核验](./verification.json)

这确认的是当前设备、签名和请求契约下的 15 条上限，不是平台对所有客户端和未来版本的永久承诺，也未验证长期稳定性或媒体播放。354 个纳入保护清单的源文件哈希未变，4 个签名进程均已退出，运行依赖副本已清理。完整请求/响应仅保存在权限受限的 `private/`；公开摘要不复制设备信息、签名和媒体地址。[保护与清理结果](./summary.json)
