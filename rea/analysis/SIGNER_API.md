# 本地签名服务 API

此服务由安装包的 `app/sign/unidbg-sign.jar` 中 `com.hongguo.sign.FqTrace` 提供，供 Python 后端在调用平台 API 前生成请求头。这里的 `X-Sign-Token` 是本地进程的访问令牌，与平台签名头、用户许可证、旧版 API key 是不同凭据。

## 服务地址与生命周期

| 场景 | 地址 |
|---|---|
| 原启动器正常启动 | 默认 `http://127.0.0.1:9099`，受 `HG_SIGN_PORT` 和端口选择逻辑影响 |
| 直接运行 Jar 的 `serve`，省略端口 | 默认 `http://127.0.0.1:9090` |
| 本次实现的导出脚本 | `127.0.0.1` 的空闲临时端口，退出时关闭 |
| 服务绑定地址 | Jar 读取 `BIND_HOST`，默认 `127.0.0.1` |

原进程启动方式（工作目录是 `app/sign`）：

```bash
java -Xmx1024m -XX:+ExitOnOutOfMemoryError \
  --add-opens java.base/java.lang=ALL-UNNAMED \
  -cp unidbg-sign.jar com.hongguo.sign.FqTrace serve 9099
```

`HG_SIGN_TOKEN` 非空时启用鉴权。原启动器以及本次脚本在每次启动生成随机令牌，再传给服务与调用方；令牌不会作为平台请求头发往 fqnovel。Java 类文件 major version 61，即需要 Java 17 或更高版本。

证据：`launcher.dis.txt:958` / `app.dis.txt:8295`；`FqTrace.javap.txt:837`（serveStatic）、`:949`（main）。本次在 Mac ARM64 上实际启动成功。

## POST /sign

这是 `FqTrace` 明确注册的唯一 HTTP context。调用方使用 POST；Java handler 本身未检查 HTTP method，协议仍应按 POST JSON 使用。

请求头：

| Header | 要求 | 说明 |
|---|---|---|
| `Content-Type` | 调用方发送 | `application/json` |
| `X-Sign-Token` | 服务启用鉴权时必需 | 必须与该服务进程的 `HG_SIGN_TOKEN` 相等 |

请求 JSON：

| 字段 | 类型 | 含义 |
|---|---|---|
| `url` | string | 平台请求完整 URL，包含 URL 编码后的 query 和 `_rticket` |
| `headers` | object<string,string> | 准备发送给平台的请求头；POST 的 `x-ss-stub` 必须已经计算好 |

```json
{
  "url": "https://api5-normal-sinfonlinec.fqnovel.com/reading/bookapi/search/tab/v?<完整查询参数>",
  "headers": {
    "user-agent": "<配置中的 user-agent>",
    "content-type": "application/json; charset=utf-8",
    "passport-sdk-version": "5051452",
    "sdk-version": "2",
    "x-tt-store-region": "kh",
    "x-tt-store-region-src": "uid"
  }
}
```

响应 HTTP 200 为签名头字典。本次实测包含：

```json
{
  "X-Argus": "<每请求生成>",
  "X-Gorgon": "<每请求生成>",
  "X-Helios": "<每请求生成>",
  "X-Khronos": "<每请求生成>",
  "X-Ladon": "<每请求生成>",
  "X-Medusa": "<每请求生成>",
  "X-Neptune": "<每请求生成>",
  "X-Soter": "<每请求生成>"
}
```

调用方把响应合并进原 headers，再发送同一 URL 与同一 body 字节。签名服务不替调用方发送平台请求，不能把 `POST /sign` 成功当成平台业务请求成功。

错误形态：

- 缺失或错误令牌：HTTP 401，`{"error":"unauthorized"}`。
- handler 异常：HTTP 200，包含 `error` 字段；必须检查 JSON，不能只检查 HTTP 状态码。
- `sign()` 返回 null 时，`signMap()` 可返回 `{}`。本次用不完整查询参数试签时实际遇到过空字典；脚本将它视为失败。
- 首次请求可能等待模拟器初始化。工作线程持有模拟器，HTTP handler 排队等待结果，因此不能据 HTTP 端口已监听推断初始化全部完成。

证据：`FqTrace.javap.txt:1048`（handler）、`:786` 附近（signMap）、`:1201`（工作线程）。

## 请求体哈希

平台 POST body 使用紧凑 JSON 的 UTF-8 字节：

```python
body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
headers["x-ss-stub"] = hashlib.md5(body_bytes).hexdigest().upper()
```

`/sign` 只收到 URL 和 headers，不单独收到平台 JSON body；它使用已计算的 body 哈希。签名后再改变 body 序列化方式会破坏一致性。

## 其他签名部署的兼容调用

Python 代码还包含向可配置 `SIGN_SERVER` 发 `GET /grab`（刷新 query/session headers）和 `GET /`（读取健康/ready/pid）的调用。这两个路径**未被随包 `FqTrace` HTTP 服务注册**，属于其他签名服务部署的兼容接口，详细调用约定见外部 API 部分。本次导出脚本仅依赖 `/sign`。
