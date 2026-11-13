# 构建小米路由器 Pro R3P

使用 Linux x86-64、上游 Padavan MIPS 工具链和 Go 1.25 或更新版。Apple Silicon 可在 ARM64 Linux 来宾中通过 Rosetta 运行 x86-64 用户空间。

Ubuntu 22.04 构建依赖包括 `build-essential`、`bc`、`bison`、`flex`、`gawk`、`autoconf`、`automake`、`autopoint`、`gettext`、`gperf`、`libtool-bin`、`libltdl-dev`、`pkg-config`、`libncurses-dev`、`texinfo`、`python3-docutils`、`xz-utils`、`fakeroot`、`unzip`、`zlib1g-dev`、`ca-certificates`、`cpio`、`file`、`dos2unix` 和 `kmod`。

先按[源码还原步骤](../r3p-v1/README.md)把完整源码和工具链解到区分大小写的文件系统。在还原出的源码根目录执行：

```sh
cd trunk
fakeroot ./build_firmware_modify MI-R3P
```

Rosetta 来宾可改用 `fakeroot-tcp`。打包时设备节点的创建和 SquashFS 的生成必须处于同一个 fakeroot 会话内。

可以在开发机运行 `make -C trunk/user/r3p`，再将生成的 `r3p-service` 复制进 Linux 环境，通过 `R3P_BINARY` 指定其绝对路径。构建环境会将其与 CA 证书包放入固件。证书路径默认采用 Linux 的 `/etc/ssl/certs/ca-certificates.crt`，可由 `R3P_CA_BUNDLE` 覆盖。

镜像生成于 `trunk/images`。当前配置使用 R3P 的 kernel0 普通布局，对应本地归档的 PB-BOOT 普通版。刷机前检查真机引导及 `/proc/mtd`，保留原固件和设置备份。

后台的「应用」页接受返回 Mihomo 原生 JSON 的 HTTPS 订阅，以及 MIPS 小端软浮点核心的 HTTPS 地址。下载文件可以是 ELF 或 gzip。首次启用和重启补缓存时使用这些地址，后续更新通过「刷新配置」触发。可选填下载文件的 SHA-256 来固定版本。切换核心地址时，原地址的校验值会清除。留空时，路由器按 HTTPS 证书验证下载，并检查核心架构和 Mihomo 配置。

WebDAV 在 LAN IPv4 上提供 HTTP 和 Basic 认证。共享目录须位于已挂载 USB 磁盘下。使用独立账号密码，可开启只读模式。
