# mihomo 本地打包与发布

日常只双击 **`打包并发布.command`**。在 Mac 上获取社区规则、合并 `custom.php`、生成完整订阅并校验，最后由你决定是否发布。服务器只需要两个文件，不再下载 GitHub 规则，也不需要缓存目录或定时抓取任务。

```text
本机 config.php + custom.php + 社区规则
  → 构建并校验
  → 终端询问：构建成功，是否发布到线上？[y/N]
      y   → FTPS 上传两个 PHP 文件 → 线上验证
      回车 / n → 只保留本地产物
```

## 使用

1. 修改本机 `custom.php` 的个人规则，或 `config.php` 的节点。
2. 双击 `打包并发布.command`，等待规则下载与校验完成。
3. 看终端输出，只有输入 `y` / `yes` 才发布，默认不发布。窗口最后等待回车关闭。
4. 发布成功后，让路由器重新获取并加载订阅。

本机需要 PHP 8.1+、Python 3 和 mihomo。本机的已验证 mihomo 核心放在 `.cache/mihomo`；也支持系统 PATH 中的 `mihomo` 或 `MIHOMO_BIN` 指定路径。没有核心时会停止发布，避免跳过配置语义校验。

可选终端用法：

```bash
./打包并发布.command --build-only          # 获取最新规则，只构建和校验
./打包并发布.command --cached              # 明确使用本地已有规则，仍询问是否发布
./打包并发布.command --cached --build-only # 使用已有规则，仅构建
```

默认每次主动更新全部社区规则；更新失败不生成或发布新包。`--cached` 可用于上游临时不可用时修改个人配置，终端会显示快照时间。非交互环境只构建，不发布；没有绕过确认的 `--yes` 参数。

## 线上两个文件

| 文件 | 用途 |
| --- | --- |
| `index.php` | 独立入口：鉴权、格式选择、完整性检查和流式输出 |
| `config.php` | 自动生成的完整规则、节点和配置数据；直接访问返回 404 |

构建产物在 `.build/`，仅上传这两个 PHP 文件。生成的 `config.php` 与本机手写的 `config.php` 不是同一个文件，**不要拿本机手写配置直接上传**。

当前 FTP 目标是 `/miwifi`，新入口：

```text
https://tools.sangonsek.com/miwifi/index.php?password=原来的订阅密码
https://tools.sangonsek.com/miwifi/index.php?password=原来的订阅密码&format=json
```

原来的 `/miwifi/public/index.php` 是旧入口。密码不变；默认 YAML，也支持 JSON、GET / HEAD，以及 `Authorization: Bearer 密码`。响应使用 `private, no-store`；未授权请求返回 401。线上 PHP 入口兼容 PHP 7.4+，不依赖源码目录、Composer、YAML 扩展或出站网络。

两个格式都包含所有 8 组规则正文，路由器不需要从 GitHub 下载规则。输出保持原生 mihomo 结构，没有额外 `data` 包装。

## FTP 信息与发布保护

FTP 设置在本机 `.deploy.local.json`，已配置好，权限为仅当前用户读写，并被 Git 忽略。不要把 FTP 密码写入 `.command` 或提交到仓库。

换电脑时，重新准备这个本地文件，字段为：

```json
{
  "host": "tools.sangonsek.com",
  "port": 21,
  "username": "你的 FTP 用户名",
  "password": "你的 FTP 密码",
  "remote_dir": "/miwifi",
  "endpoint": "https://tools.sangonsek.com/miwifi/index.php"
}
```

当前 FTP 使用自签名证书，本机设置还保存了已确认服务器的 `tls_ca_pem` 和 `tls_cert_sha256`。控制连接和数据连接均使用 TLS；证书变化会停止连接，不会自动关闭校验或降级到明文 FTP。

发布过程：

1. 本地检查生成文件、mihomo JSON/YAML 语义，以及独立 PHP 入口的鉴权和输出。
2. 终端确认后才连接 FTP；现有线上文件先备份到本机 `.deploy-backups/`。
3. 上传临时 PHP 文件，并下载比对 SHA-256；临时数据文件也有直接访问保护。
4. 校验通过后替换正式文件，只操作目标目录的两个文件，不清空目录。
5. 验证线上 JSON、YAML、版本、鉴权及 `config.php` 的 404 保护。失败自动恢复上一版；恢复也失败时明确报错，本地备份仍保留。 Nginx 附加的 HTML 404 错误页属于正常响应；仍拒绝非 404 或包含配置源码、节点内容的响应。失败时会显示具体校验原因。

服务器只读本次发布的数据，**不会自行更新规则**。要更新规则，重新双击脚本并确认发布；路由器仍需重新获取订阅。`profile-update-interval: 24` 只是客户端提示，不会替路由器建立定时任务。

## 自定义配置

在 `custom.php` 中维护，文件内有中文注释和未启用的示例：

| 字段 | 用途 |
| --- | --- |
| `direct_domains` | 域名及子域名强制直连，已配置订阅服务域名 |
| `proxy_domains` | 域名及子域名强制走代理 |
| `reject_domains` | 域名及子域名屏蔽 |
| `rules` | 额外的原生 mihomo 规则 |
| `hosts` | DNS 映射，不自动决定是否走代理 |
| `overrides` | DNS、日志等原生设置；映射递归合并，列表整体替换 |

域名只填名称，不带协议、端口、路径或通配符。策略顺序为：私有网络直连 → 个人域名例外 → 自定义原生规则 → 广告规则 → YouTube / Google / 海外规则 → 国内域名与 IP → FINAL。个人规则优先于社区规则，但仍在私有网络直连规则之后。

`overrides` 不覆盖 `proxies`、`proxy-groups`、`rule-providers`、`rules`、`hosts`。节点在本机 `config.php` 维护，其余使用专用字段。更改个人配置后需要重新构建、发布并在路由器重新加载。

## 本地代码职责

| 路径 | 用途 |
| --- | --- |
| `打包并发布.command` | 唯一日常操作入口 |
| `bin/deploy.py` | 校验、终端确认、FTPS 发布与恢复 |
| `bin/build.php` | 加载本机配置并组织构建 |
| `src/subscription.php` | 节点转换、自定义合并、mihomo 配置和 YAML 生成 |
| `src/rules.php` | 获取、校验和缓存社区规则 |
| `src/bundle.php` | 生成两个部署文件 |
| `runtime/index.php` | 独立线上入口的源模板 |
| `config.php` / `config.example.php` | 本机节点与构建设置 / 假节点示例 |
| `custom.php` | 个人配置 |
| `tests/` | 使用假节点、模拟 FTP 的测试 |

旧的 `public/index.php`、服务器动态生成逻辑和 `bin/refresh-rules.php` 已移除。`.cache/`、`.build/`、`.deploy-backups/` 和 FTP 设置均为本机运行数据，不提交 Git。

## 规则与路由器

分流数据使用 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) 的 `private`、`cn`、`google`、`youtube`、`geolocation-!cn` 域名列表和 `private`、`cn` IP 列表；广告数据使用 [anti-AD](https://github.com/privacy-protection-tools/anti-AD) 的 `anti-ad-clash.yaml`。本机下载并保持精确域名、后缀和 CIDR 语义，全部转换为 inline payload。

4 个现有节点及转换规则不变：VLESS 认证使用导出 `password`，`xtls: 2` 转为 Vision；Hysteria2 密码原样使用，TLS 验证保持开启。

服务器只提供订阅；BE7000 的 TUN、防火墙、LAN DNS 劫持和开机运行仍由 ShellCrash 等设备管理工具处理。配置中的本地监听和 IPv6 设置不等于完成整台路由器的网络接管。

## 测试

```bash
php tests/run.php
python3 tests/deployment.py
./打包并发布.command --cached --build-only
```

前两项使用假节点与规则样本，不连接真实代理或 FTP。最后一项验证本地实际完整规则包，但不会发布，也不会测试代理节点连通性。
