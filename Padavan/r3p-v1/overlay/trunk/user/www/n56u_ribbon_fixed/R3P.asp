<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>R3P 路由器</title>
<link rel="stylesheet" href="/r3p.css">
<script src="/r3p.js" defer></script>
</head>
<body>
<header class="mast">
  <a class="brand" href="/index.asp">小米路由器 Pro</a>
  <nav aria-label="主菜单">
    <a href="/index.asp">首页</a>
    <a href="#network" data-section="network">网络</a>
    <a href="#apps" data-section="apps">应用</a>
    <a href="#system" data-section="system">系统</a>
  </nav>
</header>
<main>
<section id="network" hidden>
  <h1>网络</h1>
  <p id="mode-info"></p>
  <div class="grid">
    <article><h2>Wi-Fi</h2>
      <ul><li><a href="/Advanced_Wireless2g_Content.asp">2.4 GHz Wi-Fi</a></li><li><a href="/Advanced_Wireless_Content.asp">5 GHz Wi-Fi</a></li><li><a href="/Advanced_WGuest2g_Content.asp">2.4 GHz 访客网络</a></li><li><a href="/Advanced_WGuest_Content.asp">5 GHz 访客网络</a></li></ul>
    </article>
    <article><h2>接入与局域网</h2>
      <ul><li data-router><a href="/Advanced_WAN_Content.asp">互联网接入</a></li><li><a id="lan-link" href="/Advanced_LAN_Content.asp">LAN 与管理地址</a></li><li data-router><a href="/Advanced_DHCP_Content.asp">DHCP 与地址绑定</a></li><li data-router><a href="/Advanced_IPv6_Content.asp">IPv6</a></li><li><a href="/Advanced_OperationMode_Content.asp">工作模式</a></li></ul>
    </article>
    <article data-router><h2>防火墙与转发</h2>
      <ul><li><a href="/Advanced_BasicFirewall_Content.asp">防火墙</a></li><li><a href="/Advanced_VirtualServer_Content.asp">端口转发</a></li><li><a href="/Advanced_MACFilter_Content.asp">MAC 过滤</a></li><li><a href="/Advanced_Firewall_Content.asp">访问时段与规则</a></li><li><a href="/Advanced_Netfilter_Content.asp">NAT 与连接跟踪</a></li></ul>
    </article>
    <article><h2>高级网络</h2>
      <ul><li><a href="/Advanced_Switch_Content.asp">网口与交换机</a></li><li data-router><a href="/Advanced_GWStaticRoute_Content.asp">静态路由</a></li><li data-router><a href="/Advanced_DDNS_Content.asp">DDNS</a></li><li data-router><a href="/Advanced_Modem_others.asp">USB 上网</a></li><li><a href="/Advanced_WOL_Content.asp">局域网唤醒</a></li></ul>
    </article>
  </div>
</section>
<section id="apps" hidden>
  <h1>应用</h1>
  <p id="request-error" class="error" role="alert"></p>
  <div class="grid">
    <article><h2>Mihomo</h2>
      <p id="proxy-state" role="status">正在获取状态…</p>
      <p id="proxy-message" class="muted"></p>
      <div class="actions">
        <button type="button" data-action="proxy-on">启用代理</button>
        <button type="button" data-action="proxy-off" class="secondary">关闭</button>
        <button type="button" data-action="proxy-refresh" class="secondary">刷新配置</button>
      </div>
      <details>
        <summary>代理参数</summary>
        <form data-action="proxy-save">
          <label>核心 HTTPS 地址<input type="url" name="core" maxlength="1024" autocomplete="off"></label>
          <label>下载文件的 SHA-256<input name="sha256" maxlength="64" spellcheck="false" autocomplete="off"></label>
          <label>JSON 订阅 HTTPS 地址<input type="url" name="subscription" maxlength="1024" autocomplete="off"></label>
          <small>已有设置时，留空保留原值。</small>
          <button type="submit">保存地址</button>
        </form>
      </details>
    </article>
    <article><h2>广告过滤与代理规则</h2>
      <p class="muted">从订阅读取分流和广告规则。启用代理后可切换节点及各分组策略。</p>
      <div id="proxy-groups"></div>
      <details><summary>本机规则</summary>
        <form data-action="rules-save">
          <label>拦截域名<textarea name="block" rows="3" spellcheck="false"></textarea></label>
          <label>广告例外域名<textarea name="allow" rows="3" spellcheck="false"></textarea></label>
          <label>代理规则<textarea name="rules" rows="3" spellcheck="false"></textarea></label>
          <small>每行一条。域名支持其子域名。分流示例 <code>DOMAIN-SUFFIX,example.com,DIRECT</code>。</small>
          <label>绕过代理的设备 IP<textarea name="bypass_clients" rows="2" spellcheck="false"></textarea></label>
          <label>绕过代理的目标网段<textarea name="bypass_destinations" rows="2" spellcheck="false"></textarea></label>
          <small>每行填写一个 IPv4、IPv6 或 CIDR，例如 <code>192.168.1.8</code>。</small>
          <button type="submit">保存本机规则</button>
        </form>
      </details>
    </article>
    <article><h2>文件与媒体</h2>
      <ul><li><a href="/Advanced_AiDisk_samba.asp">Samba 文件共享</a></li><li><a href="/Advanced_AiDisk_others.asp">miniDLNA 与硬盘设置</a></li><li><a href="/index.asp">USB 磁盘与安全弹出</a></li></ul>
    </article>
    <article><h2>WebDAV</h2>
      <p id="dav-state" role="status">正在获取状态…</p>
      <p id="dav-message" class="muted"></p>
      <p><a id="dav-url"></a></p>
      <form data-action="dav-save">
        <label class="check"><input type="checkbox" name="enabled" value="1">局域网 WebDAV</label>
        <label>共享目录<input name="path" list="dav-mounts" placeholder="/media/磁盘名/目录" maxlength="320"></label>
        <datalist id="dav-mounts"></datalist>
        <label>端口<input name="port" type="number" min="1024" max="65535" value="8082" required></label>
        <label>独立用户名<input name="user" maxlength="64" autocomplete="off"></label>
        <label>独立密码<input name="password" type="password" maxlength="128" placeholder="留空保留已有密码" autocomplete="new-password"></label>
        <label class="check"><input type="checkbox" name="readonly" value="1">只读共享</label>
        <button type="submit">保存 WebDAV</button>
      </form>
    </article>
  </div>
</section>
<section id="system" hidden>
  <h1>系统</h1>
  <div class="grid">
    <article><h2>管理与服务</h2><ul><li><a href="/Advanced_System_Info.asp">设备与运行状态</a></li><li><a href="/Advanced_System_Content.asp">账号、设备名与时间</a></li><li><a href="/Advanced_Services_Content.asp">SSH 与系统服务</a></li></ul></article>
    <article><h2>诊断与统计</h2><ul><li><a href="/Main_LogStatus_Content.asp">系统日志</a></li><li><a href="/Main_TrafficMonitor_realtime.asp">实时流量</a></li><li><a href="/Main_TrafficMonitor_last24.asp">最近 24 小时流量</a></li><li><a href="/Advanced_Scripts_Content.asp">维护脚本</a></li><li><a href="/Advanced_InetDetect_Content.asp">网络连通性检测</a></li></ul></article>
    <article><h2>升级与恢复</h2><ul><li><a href="/Advanced_FirmwareUpgrade_Content.asp">升级固件</a></li><li><a href="/Advanced_SettingBackup_Content.asp">备份与恢复</a></li><li><a href="/Advanced_Tweaks_Content.asp">LED 与实体按键</a></li></ul></article>
  </div>
</section>
</main>
<span id="r3p-mode" hidden><% nvram_get_x("", "sw_mode"); %></span>
</body>
</html>
