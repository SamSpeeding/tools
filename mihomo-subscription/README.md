# mihomo 订阅服务

PHP 8.1+，无需数据库、Composer 或额外 PHP 扩展。一个带密码的 GET 接口生成 mihomo 配置，可返回 YAML 或 JSON。

## 已配置的内容

- 本机 `config.php` 已写入 4 个节点：Fast2-Reality、Fast2-Hysteria2、SG-Reality、SG-Hysteria2，以及随机生成的固定访问密码。
- 主配置包含节点、策略组、个人规则、DNS 和社区规则集引用。
- 分流规则来自 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)，广告规则来自 [anti-AD](https://github.com/privacy-protection-tools/anti-AD)。使用 MRS 格式，建议使用当前稳定版 mihomo。
- PHP 每次 GET 根据本地配置生成订阅。**这一版不在 PHP 服务器上抓取、合并或镜像规则正文**；mihomo 根据返回的 `rule-providers` 自行下载规则，默认每 24 小时更新。支持通过配置的代理下载，PHP 主机无需访问 GitHub。
- `format=json` 返回同一份 mihomo 配置结构；没有额外的 `data` 包装，不包含接口访问密码。它仍然引用远程规则文件。

## 本地启动

```bash
cd /Users/tt/tools/mihomo-subscription
php -S 127.0.0.1:8787 -t public
```

查看 `config.php` 第 6 行的 `access_password`，将其替换到以下地址：

```text
http://127.0.0.1:8787/index.php?password=你的访问密码
http://127.0.0.1:8787/index.php?password=你的访问密码&format=json
```

订阅客户端使用第一个地址。接口也支持 `Authorization: Bearer 你的访问密码`，便于支持请求头的客户端避免把密码放进 URL。密码有特殊字符时，查询参数须做 URL 编码。

`127.0.0.1` 只供本机验证。路由器订阅时使用部署后的 HTTPS 地址。

## 部署

1. 上传整个 `mihomo-subscription` 目录，网站文档根目录指向它的 **`public/` 子目录**；入口是 `index.php`。
2. 随代码上传 `config.php`。此文件包含写死的访问密码和节点信息，按本私有仓库的使用方式允许纳入 Git 版本管理；提交后可随代码一起拉取部署。没有现成配置时，把 `config.example.php` 复制成 `config.php` 并修改。
3. 确保 PHP 运行用户可读 `config.php`，网站启用 HTTPS。只有带正确密码的 GET / HEAD 会返回配置。
4. 订阅 URL 为 `https://你的域名/index.php?password=你的访问密码`。若网站已有其他服务，可为本服务配置独立域名或将对应路径映射到 `public/`。

访问密码独立于各节点的认证密码，修改 `access_password` 只影响订阅获取。服务不需要可写缓存目录；响应使用 `Cache-Control: private, no-store`。用 URL 密码时，可在 Web 服务器访问日志中省略查询参数。

## 分流与节点选择

规则顺序如下：

1. 私有域名和私有 IP 直连。
2. `direct_domains`、`proxy_domains`、`reject_domains` 中的个人域名后缀例外，依次匹配。
3. anti-AD 命中项交给 `ADS`，默认拦截；面板中选 `DIRECT` 可临时关闭广告拦截。
4. YouTube、Google 和其他海外域名规则走代理。
5. 国内域名、国内 IP 直连。
6. 其他请求交给 `FINAL`，默认走代理，也可切换到直连。

`PROXY` 默认选择 `AUTO`。AUTO 每 300 秒对节点做探测，按探测延迟选择线路；也可在 PROXY、GOOGLE、YOUTUBE 中手动指定节点。探测延迟不是实际网站带宽。规则过滤无法保证去掉与正常内容共用域名的视频广告。

需要固定直连的域名写入 `direct_domains`，例如 `example.com`；这也会放行其子域名。不要填写 URL、端口或逗号。遇到广告误拦时可在这里添加例外。避免在多个个人列表中重复配置同一域名。

## 节点转换

`nodes` 使用用户提供的导出字段格式；只转换所需字段：

- VLESS 的 `password` → mihomo 的 `uuid`；导出中的顶层 `uuid` 是客户端记录 ID，不作为认证值。
- `xtls: 2` → `flow: xtls-rprx-vision`，`xtls: 0` 不设置 flow。
- `peer` → VLESS 的 `servername` / Hysteria2 的 `sni`。
- `publicKey`、`shortId` → `reality-opts`；`tlsProfile` → `client-fingerprint`。
- Hysteria2 的 `password` 原样使用；`obfs: none` 不生成混淆字段。
- `created`、`updated`、`ping`、客户端记录 ID 等元数据不进入配置。

目前转换器支持 VLESS Reality TCP 和无混淆 Hysteria2，不能直接导入其他协议或传输方式。保留证书验证，不跳过 TLS 校验。

## 更新与路由器接入

社区规则的 24 小时更新由 mihomo 核心负责。更改本服务的节点、个人例外或分流结构，需要客户端重新获取**整份订阅并加载**；配置客户端的定时订阅更新，或由路由器管理工具执行下载、校验、替换和加载。响应头 `profile-update-interval: 24` 只是给兼容客户端的提示，不会自动替 mihomo 核心安排主配置更新。

本服务输出可由 mihomo 读取的基础配置，默认本机代理端口为 `127.0.0.1:7890`、DNS 为 `127.0.0.1:1053`。**它不直接配置 BE7000 的防火墙、TUN、LAN DNS 劫持或开机服务**；这些交给 ShellCrash 等设备管理工具，并按设备情况调整入站及 DNS 设置。配置中的 `ipv6: false` 也不等于关闭路由器或终端的 IPv6。

更新时应保留上一次有效主配置；下载或校验失败不覆盖旧文件。

## 验证

```bash
php tests/run.php
php -l public/index.php
php -l src/subscription.php
```

测试使用假节点，不访问真实代理。可另用 mihomo 的 `-t -f 配置文件路径 -d 工作目录` 检查生成文件；配置解析成功不代表节点已连通或路由器已经接管流量。

参考：[mihomo VLESS](https://wiki.metacubex.one/config/proxies/vless/)、[Hysteria2](https://wiki.metacubex.one/config/proxies/hysteria2/)、[规则集合](https://wiki.metacubex.one/config/rule-providers/)、[DNS](https://wiki.metacubex.one/config/dns/)。
