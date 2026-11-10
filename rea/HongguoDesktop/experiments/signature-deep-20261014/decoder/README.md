# Helios / Medusa 离线解码记录（2026-10-14）

本目录只读取已保存请求与候选签名，不发送网络请求、不启动签名器、不改应用或原脚本。独立工具使用 Python 脚本中的加密原语并编写其逆过程；没有载入目标 PYC。可识别的设备 ID、完整签名、完整 protobuf 只保存于权限 `0700` 的 `private/`，其文件为 `0600`。

## 已确认的差异

| 项目 | 原 JAR | 参考 Python 脚本 |
|---|---|---|
| Helios 明文格式 | `khronos-1611921764-3019` | `khronos-1588093228-8662` |
| Helios key 派生输入 | 样本用 `随机前缀 + "8662"` 可正确还原 | 源码明确使用 `随机前缀 + "8662"` |
| Helios 验证 | 解密后重新加密，完整签名逐字节相同 | 同左 |
| Medusa 可见 envelope 版本 | `4` | `3` |
| Medusa envelope 后 16 字节标识 | `126f8075e685b236b8eb84ca22cb43e8` | `f7e85ffad7d7dc3bd62ac87057cf6118` |
| Medusa envelope flag | `256` | `256` |
| Medusa 内层还原 | 未完成；不能套用 v3 后断言字段值 | 已还原 protobuf、验证绑定并完成整包逐字节回环 |

Helios 第二、第三个位置按参考源码和同一脚本 Medusa schema 对应 `license_id`、`ms_app_id/aid`；JAR 实测能够确证的是上述位置值，不代表已经证明其 native 内部变量名或 3019 的产品归属。这里的 `license_id` 是平台签名上下文的字段，不是原下载器作者的收费激活码。

脚本的 `_encrypt_helios` 明文构造见 `/Users/tt/Downloads/红果短剧.py:3183`；key 派生见同文件 `3165`；Medusa envelope 构造见 `3277`。JAR 生成位置值与 URL 的 `aid=8662` 不同是确定事实，但该差异是否单独导致服务端拒绝，应以主实验的在线字段隔离结果为准，不能只从静态不一致推断。

## Medusa v3 已验证内容

逆过程包括去除时间戳 XOR envelope、从密文所嵌入位提取 32 字节 AES 变体密文、恢复原始位、反转种子 XOR 和字节顺序、反转 `_xmxor`、解析 protobuf。使用恢复出的 protobuf 和随机数重新经过原正向函数，最终 Base64 签名逐字节一致。

`AES_V3` 在参考源码中带 decrypt 方法，但 `inv_s_box` 只分配而未填充。工具仅为本进程导入的模块填好四组逆 S-box；没有修改源脚本。

解出的 v3 真实包含这些字段：

- 顶层 `ms_app_id`、`device_id`、`license_id`、App 版本、SDK 字符串与数值版本、两份时间戳。
- `env.device` 再次包含 App ID 和设备 ID，以及系统版本、机型、品牌、时区、内存、存储、电池、采样时间等。
- `env` 包含 PID、launch_time、SDK 环境版本、App 版本和 report。
- 原始 URL query 的 SM3 截断、query/body/time 的组合摘要、query/body 的完整 SM3。设备信息和请求参数确实进入签名内文，而非仅拼进 URL。

每个已审计 v3 候选都核对：App ID 与 URL aid、内外两层设备 ID 与 URL、App 版本、两份 khronos、body MD5、query SM3、query/body/time hash 和 query/body SM3。公开结果只记录布尔匹配，不输出 ID 或摘要原值。

固定环境采样值（例如脚本的 report_ts）仍确实存在。能够成功返回不代表这些采样值真实、可长期复用，也不代表设备注册生命周期已经弄清。

## 证据与重复执行

- `capture-audit.json`：最终候选签名审计涵盖 43 组（每组 JAR/Python 两套，共 86 对 Helios/Medusa）。43 个 JAR Helios 都是 `3019/1611921764`，43 个 JAR Medusa envelope 都为 v4；43 个 Python Medusa v3 都完成全包回环，所有请求绑定检查通过。Python Helios 中有 3 组 phase08 人为字段变更，不能把它们当原脚本默认输出。包含 phase07 至 phase10 新跨集、多 VID、字段隔离、重复请求。
- `sent-request-audit.json`：单独审计 83 个实际发出的模型请求（含之前各阶段）。83 个 Helios 全部回环通过；66 个实际 Medusa v3 全包回环和全部绑定检查通过；17 个 v4 仅确认 envelope。83 个请求的保存签名都与 `wire_headers` 真正发出的头一致。删去 Helios 的历史诊断请求和本轮 2 个详情请求不在这个计数内。本轮 39 个模型请求均在审计中。
- `offline-validation.json`：14/14 个纯本地测试通过，覆盖 4 种 AES selector、嵌入位恢复、不同长度的 `_xmxor` 逆过程以及两种 Helios 内文。
- `private/*-decoded.json`：私有逐字段 protobuf 和 Helios 解码。

## 严格字段隔离的实际报文核验

主任务 phase09 发出的 5 个请求，都由本目录再次解码实际 `request.headers`。以下项目逐条相同：URL、body、除 `x-helios` 外的全部 headers、Helios 随机前缀和内部 khronos。并且逐条核对 `wire_headers`，排除了“候选签名改变、真正发出仍是旧签名”的情况。

| 实际 Helios license_id | 实际 Helios app_id | 结果 |
|---|---|---|
| `1611921764`（首先发送） | `8662` | `110001` |
| `1588093228` | `8662` | `0` |
| `1588093228` | `3019` | `0` |
| `1611921764` | `3019` | `110001` |
| `1588093228`（与第二条完全相同签名重放） | `8662` | `0` |

因此，在保持 Python Medusa v3 和此组请求上下文不变的条件下，Helios 的 license_id 位置改变已经能解释这组结果；app_id 位置单独变成 3019 没有导致失败。这是有控制组、恢复组的观察，不是从字段名猜测。

主任务另做了“正确 Python Helios + 原 JAR Medusa”的对照仍失败。故不能把所有差异都简化成只修 Helios 的 license_id；Medusa 的独立问题仍需保留，而且不能把“v4”这个版本号本身直接等同于错误原因。

重复审计（会更新本目录审计 JSON 和私有解码）：

```sh
/Users/tt/Desktop/rea/HongguoDesktop/.runtime/python/bin/python3.11 -B /Users/tt/Desktop/rea/HongguoDesktop/experiments/signature-deep-20261014/decoder/audit_captures.py
```

可导入 `decode_helios(header)`、`medusa_envelope(header, khronos)`、`decode_medusa(header, khronos)`。最后一个只验证了 v3；不要对 JAR v4 强行解析。`decode_helios` 的 `app_id` 参数指 key 派生用的 seed 字符串，与还原出来的明文第三位置必须分开理解。

## 尚未确认

JAR Medusa v4 的 protobuf、其内部 device_id/aid/license/App/SDK 版本尚未还原；不能声称它们一定与 Helios 相同。v3 的已知 key/iv/AES 变体不能对这一 v4 样本完成回环，这说明当前 decoder 不适用，不能据此判定 v4 签名本身非法。要进一步确认，需要定位 native 的 v4 key/算法或在其序列化、加密边界取证；这些工作本目录没有实施。
