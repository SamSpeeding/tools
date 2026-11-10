"""Assemble the complete API reference and check explicit local-route coverage."""
from pathlib import Path
import json
import re

BASE = Path(__file__).resolve().parents[1]
routes = json.loads((BASE/'evidence/local-routes.json').read_text())
local = (BASE/'LOCAL_API.md').read_text()
remote = (BASE/'REMOTE_API.md').read_text()
signer = (BASE/'SIGNER_API.md').read_text()
encryption = (BASE/'VIDEO_ENCRYPTION.md').read_text()
remote_routes = json.loads((BASE/'evidence/remote-routes.json').read_text())['routes']
local_headings = set(re.findall(r'^### \d+\. (GET|POST|DELETE) `([^`]+)`$', local, re.MULTILINE))
missing = [f"{r['method']} {r['path']}" for r in routes if (r['method'], r['path']) not in local_headings]
if missing:
    raise SystemExit('Local API documentation missing route sections: ' + ', '.join(missing))
missing_remote = [r['id'] for r in remote_routes if not re.search(r'^#### `' + re.escape(r['id']) + r'`', remote, re.MULTILINE)]
if missing_remote:
    raise SystemExit('Remote API documentation missing route sections: ' + ', '.join(missing_remote))

intro = '''# HongguoDownloader API 文档

对象：`HongguoDownloader-Setup.exe`，版本 **1.0.0.72**。整理日期：2026-10-12。

本文整理该安装包业务层可恢复的全部 HTTP 接口，覆盖本地 FastAPI 路由、本地签名器、APP 平台、公开网页、目录服务、许可证、支付和更新调用。每个接口尽可能标出方法、参数、响应、鉴权、调用关系和代码证据；动态字段与尚未运行验证的行为单独说明。

## 阅读入口

- [一、本地服务接口](#local-api)：**70 个业务层明确注册的 method/path**，GET 40、POST 29、DELETE 1；另有 FastAPI 自动生成的 4 个文档路径，各支持 GET/HEAD。安装版路径过滤允许50个业务接口，屏蔽其余20个以及4个框架文档路径。允许通过路径过滤不等于满足令牌或许可证条件。
- [二、本地签名服务](#signer-api)：Jar 注册的 `/sign`，本次已运行验证。
- [三、外部服务接口](#remote-api)：**33 个出站路径／模板**，包含 8 个不同的 APP 业务路径，以及网页、目录、许可证、支付、更新和兼容签名服务调用。这是客户端使用到的接口范围，不代表远端服务的全部接口。
- [四、视频加密与下载后处理](#video-encryption)：原程序如何从加密 MP4 得到最终文件，以及当前导出脚本的能力边界。
- [搜索至全剧地址的详细流程](REQUEST_CHAIN.md)。

### 已实测范围

本次重写脚本在 Mac ARM64 上成功启动提取出的 Java 签名器。关键词“逆袭”选中 `series_id=7689391720735181848` 后，成功取得 **111/111 集地址、555 条清晰度记录**；25 个平台请求与25个签名请求均 HTTP 200。第 1、56、111 集的 CDN 链接各读128字节，均 HTTP206 且为MP4文件头。

测试样本的全部 555 条清晰度记录均为 `encrypt_info.encrypt=true`、`encryption_method="cenc-aes-ctr"`，下载URL有有效期。该结果证明本次样本的目录、地址覆盖率及抽查链接可读性。主导出脚本没有执行解密；随后已另行完成《坠崖捡个参娃娃》第 1 集的下载、解密、重封装和完整音视频解码验证，详见第四部分，不能把单集结果外推为所有剧集已验证。

其余接口按字节码和界面代码静态还原；支付、许可激活、文件删除、安装更新等接口没有为编写文档而触发。本地原 FastAPI 服务和 Windows EXE 未运行，不能把静态路由信息写成其运行抓包结果。

### 证据与复核

- 安装包 SHA-256：`9d77a2548cc1bde92c4a269a3f482655b4f5fc538421f328af8d959d6739b592`。
- [REA 完整证据](evidence/rea-evidence.json)：安装包 artifact inspection、提取网页 JavaScript 静态分析，4 条保留记录。
- Python 3.11 字节码用 xdis 静态反汇编；Java 用 javap 检查。未将辅助工具输出冒充 REA 原生 Python 反编译能力。
- [本地路由清单](evidence/local-routes.json)、[独立枚举与鉴权审计](evidence/api-audit.md)、[外部接口清单](evidence/remote-routes.json)。
- [本次50条请求记录](../outputs/requests.jsonl)、[CDN抽查结果](evidence/live-verification.json)、[完整剧信息及地址](../outputs/逆袭111集.json)。

文中 `*.dis.txt:行号` 指已保存反汇编文本的物理行号，`源行` 指 pyc 中携带的原源码行号；这两者不是同一套行号。接口成功通常还要求业务状态码成功，HTTP200本身不足以判定。

'''

def section(anchor, title, content):
    content = re.sub(r'^# .*\n', '', content, count=1).lstrip()
    content = re.sub(r'^(#{2,5}) ', r'#\1 ', content, flags=re.MULTILINE)
    return f'<a id="{anchor}"></a>\n\n## {title}\n\n' + content + '\n\n'

output = intro + section('local-api','一、本地服务接口',local) + section('signer-api','二、本地签名服务',signer) + section('remote-api','三、外部服务接口',remote) + section('video-encryption','四、视频加密与下载后处理',encryption)
path = BASE/'API文档.md'
path.write_text(output)
print(f'{path}: {len(output.splitlines())} lines; all {len(routes)} local and {len(remote_routes)} remote route sections present')
