---
status: accepted
---

# 使用 Tauri 界面并保留 Python 媒体处理链路

桌面应用采用用户指定的 Tauri，业务请求、签名协作、下载、解密和校验继续使用已有 Python 链路。保留这条链路可复用已验证的协议与媒体处理实现，代价是应用除桌面外壳外仍需要 Python、Java 和 FFmpeg，不能以 Tauri 外壳体积推断成品体积。

首轮验收只要求这台 ARM64 Mac 上 Finder 双击可运行，允许使用本机 Java/FFmpeg。独立分发和 Windows 支持需要各自的运行时打包与实际验收，不由本机成功直接推定。
