# R3P 定制首版源码

基于 `hanwckf/rt-n56u` 的 `23387b278a7cf728748af606760758f5d59d1451`。`overlay/trunk/user/r3p/` 是 Mihomo 管理和 WebDAV 服务。`overlay/trunk/user/scripts/r3p-firewall.sh` 配置双栈透明代理。`overlay/trunk/user/www/n56u_ribbon_fixed/` 是新后台页面。`upstream.patch` 包含对上游构建配置、内核模板、启动服务、防火墙和后台的改动。

完整的上游源码和交叉工具链在 [`../rt-n56u`](../rt-n56u/README.md)。还原源码需要 Git、`zstd`、`tar` 和区分大小写的文件系统。用 Bash 从 `tools/Padavan/r3p-v1` 执行下列命令，把 `/path/to/r3p-source` 改成一个尚未存在的目录。

```sh
set -euo pipefail
r3p_customization="$PWD"
r3p_archive="$r3p_customization/../rt-n56u"
r3p_source=/path/to/r3p-source
(cd "$r3p_archive" && shasum -a 256 -c SHA256SUMS.txt)
mkdir "$r3p_source"
cat "$r3p_archive"/rt-n56u-23387b278.tar.zst.part-* |
  zstd -dc | tar -xf - -C "$r3p_source"
cd "$r3p_source"
git apply --check "$r3p_customization/upstream.patch"
git apply "$r3p_customization/upstream.patch"
cp -Rp "$r3p_customization/overlay/." .
mkdir toolchain-mipsel/toolchain-3.4.x
tar -xJf "$r3p_archive/mipsel-linux-uclibc.tar.xz" -C toolchain-mipsel/toolchain-3.4.x
```

Go 依赖已随源码保存。还原过程可离线执行。装好 Linux 构建环境后，按[构建说明](../docs/r3p-build.md)生成 PB-BOOT 普通版 `kernel0` 布局镜像。首版镜像和 SHA-256 清单在 [`../firmware/`](../firmware/)，试装步骤和实测结果见 [R3P 定制方案](../R3P-Padavan-定制方案.md)。
