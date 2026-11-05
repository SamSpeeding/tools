# mihomo 全量订阅服务

PHP 8.1+，一个带密码的 GET 接口返回完整的 mihomo YAML 或 JSON 配置，包含节点、策略组、DNS、个人配置和 **8 组社区规则正文**。路由器获取这份配置后，无需再向 GitHub 下载规则文件。

社区规则来自 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) 和 [anti-AD](https://github.com/privacy-protection-tools/anti-AD)。PHP 服务端负责下载、校验和缓存，然后生成 `type: inline` 的 `rule-providers`。无需数据库、Composer、YAML 或 Zstandard 扩展。

## 文件职责

| 文件 | 用途 |
| --- | --- |
| `public/index.php` | 唯一 HTTP 入口，校验访问密码并输出订阅 |
| `config.php` | 访问密码、4 个节点和服务端缓存设置 |
| `custom.php` | 日常编辑的个人域名、额外规则、hosts 和配置覆盖 |
| `config.example.php` | 不含真实凭证的配置示例 |
| `src/subscription.php` | 节点转换、自定义配置合并、JSON/YAML 输出 |
| `src/rules.php` | 固定社区来源、下载校验、完整快照缓存 |
| `bin/refresh-rules.php` | CLI 预热或强制刷新社区规则缓存 |
| `.cache/` | 自动生成的公共规则缓存，不含节点或订阅密码，已忽略 Git 提交 |

## 部署与访问

1. 上传整个目录，保留自己的 `config.php` 和 `custom.php`。网站文档根目录应指向 **`public/`**，或者将现有网站的对应路径映射到该目录。
2. PHP 运行用户需要可读配置、可读写 `.cache/`；缓存目录放在 `public/` 外。CLI 预热和 Web PHP 最好使用同一系统用户，避免新缓存无法被另一方读取。
3. PHP 服务器需要能通过 HTTPS 访问 `raw.githubusercontent.com`。支持 PHP cURL；没有 cURL 时使用 OpenSSL HTTPS streams，需要开启 `allow_url_fopen`。启用网站 HTTPS。
4. 建议首次部署时先预热缓存，避免第一次 HTTP 请求等待全部下载：

```bash
php /你的部署目录/mihomo-subscription/bin/refresh-rules.php
```

CLI 强制刷新最多等待 180 秒；输出各规则集条数和更新时间，不输出节点凭证。更新失败返回非零退出码，同时保留原有完整缓存。

部署路径和密码不变时，原订阅地址继续使用：

```text
https://你的域名/miwifi/public/index.php?password=你的访问密码
https://你的域名/miwifi/public/index.php?password=你的访问密码&format=json
```

默认输出 YAML；`format=json` 输出相同的原生 mihomo 对象，没有 `data` 包装。二者均包含规则正文，不包含订阅访问密码。也支持 `Authorization: Bearer 你的访问密码`，请求头优先于查询参数。只接受带正确密码的 GET / HEAD，响应为 `Cache-Control: private, no-store`。

现有 `config.php` 按本私有仓库的使用方式允许提交；从零部署时复制 `config.example.php` 并填写密码、节点即可。访问密码独立于节点密码。

**如果 PHP 服务器也无法访问 GitHub**，需要先解决服务器的上游连通性；也可以在能访问 GitHub 的电脑运行刷新脚本，再上传 `.cache/rules-v1.json` 并设置读取权限。后者只是提供初始快照，后续更新仍需在能访问上游的环境执行。

本地验证：

```bash
cd /Users/tt/tools/mihomo-subscription
php bin/refresh-rules.php
php -S 127.0.0.1:8787 -t public
```

访问 `http://127.0.0.1:8787/index.php?password=你的访问密码`。路由器应使用部署后的 HTTPS 地址。

## 自定义配置

日常只编辑 `custom.php`。文件返回 PHP 数组，例如：

```php
<?php
return [
    'direct_domains' => [
        'tools.sangonsek.com', // 订阅域名直连
        'example.cn',
    ],
    'proxy_domains' => ['example.com'],
    'reject_domains' => ['ads.example.com'],
    'rules' => [
        'IP-CIDR,203.0.113.7/32,PROXY,no-resolve',
    ],
    'hosts' => [
        'nas.home.arpa' => '192.168.31.100',
    ],
    'overrides' => [
        'log-level' => 'warning',
        'dns' => [
            'nameserver-policy' => [
                '+.internal.example.com' => ['192.168.31.1'],
            ],
        ],
    ],
];
```

除实际订阅域名外，仓库里的示例均已注释，不会自动启用。

- `direct_domains`、`proxy_domains`、`reject_domains`：分别强制直连、走代理、屏蔽。填写域名后缀，包含其子域名；不要填写 URL、端口或通配符。这些列表追加到 `config.php` 的原有例外之后。
- `rules`：额外的原生 mihomo 规则，按填写顺序放在个人域名规则之后、社区规则之前。目标可用 `DIRECT`、`REJECT`、`PROXY`、`GOOGLE`、`YOUTUBE` 等已存在的策略组。不要随意添加 `MATCH`，否则后续社区规则不再匹配。PHP 检查基本格式，完整语义由 mihomo 校验。
- `hosts`：DNS 映射；仅设置映射不等于选择直连或代理，按需同时添加域名规则。
- `overrides`：原生 mihomo 设置，键值映射递归合并，列表整体替换，标量覆盖。可用于 DNS、日志级别等。禁止覆盖 `proxies`、`proxy-groups`、`rule-providers`、`rules`、`hosts`，以免丢失生成的节点或内嵌规则；节点继续在 `config.php` 中维护，规则和 hosts 使用专用字段。

自定义内容每次请求重新读取，不受社区规则缓存有效期影响。修改后，路由器需要**重新下载并加载整份订阅**才生效。自定义文件缺失时使用默认配置；未知字段或明显格式错误返回 HTTP 500，不静默忽略。先运行 `php -l custom.php` 检查 PHP 语法，再校验生成的 mihomo 配置。

## 分流顺序

1. 私有域名、私有 IP 直连。
2. 个人直连、代理、屏蔽域名依次匹配；不要把同一域名放进多个列表。
3. `custom.php` 的额外 `rules`。
4. anti-AD 命中项交给 `ADS`，默认拦截；面板选择 `DIRECT` 可临时关闭这部分广告拦截。
5. YouTube、Google、其他海外域名走代理。
6. 国内域名、国内 IP 直连。
7. 其他请求交给 `FINAL`，默认走代理，可切换为直连。

个人例外优先于社区广告、分流规则，但私有网络直连规则仍在最前。`PROXY` 默认选择 `AUTO`；AUTO 每 300 秒探测节点并按延迟选择，实际网站带宽需另测。规则过滤无法保证去掉与正常内容共用域名的视频广告。

## 社区来源与缓存

MetaCubeX 使用以下文本列表，基础地址为：

```text
https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/
```

| 规则集 | 路径 |
| --- | --- |
| private-domain | geosite/private.list |
| private-ip | geoip/private.list |
| cn-domain | geosite/cn.list |
| cn-ip | geoip/cn.list |
| google | geosite/google.list |
| youtube | geosite/youtube.list |
| overseas | geosite/geolocation-!cn.list |

广告列表来自 [anti-ad-clash.yaml](https://raw.githubusercontent.com/privacy-protection-tools/anti-AD/master/anti-ad-clash.yaml)。源地址固定在服务端，不接受请求参数指定下载地址。保留精确域名、`+.` 后缀和 IPv4/IPv6 CIDR 的原始匹配语义。

- 缓存默认有效 24 小时，通过 `rule_update_interval` 调整。
- 缓存过期后由一次请求刷新；HTTP 刷新总预算默认 25 秒，单次下载上限 15 秒，可在 `config.php` 调整。单个源限制 16 MiB。
- 所有 8 组规则下载、解析和校验成功才原子替换缓存；空数据、HTML 错误页、无效条目或部分失败都不会覆盖旧快照。
- 更新失败或其他请求正在更新时，继续输出上次完整规则；失败后 5 分钟内不重复触发普通刷新。CLI 强制刷新不受此退避限制。
- 没有有效完整缓存且无法成功下载时返回 HTTP 503，不返回缺失规则的配置。
- 响应头 `X-Rules-Updated-At` 表示快照更新时间；`X-Rules-Cache: fresh` / `stale` 表示是否过期。

## 定时更新与路由器接入

**改成内嵌规则后，路由器必须定期更新整份订阅，规则才会更新。** 建议 PHP 服务器每天定时执行 `bin/refresh-rules.php`，ShellCrash 或路由器脚本随后下载并重载订阅。响应头 `profile-update-interval: 24` 只是给兼容客户端的提示，不会自动给 mihomo 核心安排定时任务。

更新流程应为：下载到临时文件 → 确认 HTTP 成功 → 用 mihomo `-t` 校验 → 替换并重载。下载或校验失败保留路由器上一次有效配置。

本服务仍输出基础配置：代理监听 `127.0.0.1:7890`、DNS 监听 `127.0.0.1:1053`。BE7000 的防火墙、TUN、LAN DNS 劫持和开机服务由 ShellCrash 等设备管理工具按运行模式配置；`ipv6: false` 不等于关闭整个路由器或终端的 IPv6。

## 节点转换

4 个现有节点及转换规则保持不变：

- VLESS 的导出字段 `password` → mihomo `uuid`；导出顶层 `uuid` 是客户端记录 ID。
- `xtls: 2` → `flow: xtls-rprx-vision`，`xtls: 0` 不设置 flow。
- `peer` → VLESS `servername` / Hysteria2 `sni`。
- `publicKey`、`shortId` → `reality-opts`；`tlsProfile` → `client-fingerprint`。
- Hysteria2 密码原样使用；`obfs: none` 不生成混淆字段。保留 TLS 证书验证。
- 时间、延迟等客户端记录元数据不进入最终配置。

仅支持现有 VLESS Reality TCP 和无混淆 Hysteria2，其他协议需要扩展转换器。

## 验证

```bash
php tests/run.php
php -l public/index.php
php -l custom.php
php bin/refresh-rules.php
mihomo -t -f 生成的配置.yaml -d 临时工作目录
```

自动测试使用假节点和上游样本，覆盖个人配置合并、认证、完整缓存、部分失败、并发刷新、失败退避和冷启动错误。刷新脚本会访问真实公共规则源；配置解析成功不代表真实节点已经连通或路由器已经接管流量。

参考：[mihomo 内嵌规则集合](https://wiki.metacubex.one/config/rule-providers/)、[规则顺序](https://wiki.metacubex.one/config/rules/)、[hosts](https://wiki.metacubex.one/config/dns/hosts/)、[DNS](https://wiki.metacubex.one/config/dns/)。
