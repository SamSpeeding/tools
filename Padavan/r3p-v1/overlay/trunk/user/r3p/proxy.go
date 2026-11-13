package main

import (
	"bufio"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

const proxyMarker = runDir + "/proxy.active"
const proxyReady = runDir + "/proxy.ready"
const controlURL = "http://127.0.0.1:17890"

type proxyProcess struct {
	cmd  *exec.Cmd
	done chan struct{}
	dir  string
}

func (p *proxyProcess) exited() bool {
	select {
	case <-p.done:
		return true
	default:
		return false
	}
}

func (p *proxyProcess) stop() {
	if !p.exited() {
		p.cmd.Process.Signal(syscall.SIGTERM)
		select {
		case <-p.done:
		case <-time.After(time.Second):
			p.cmd.Process.Kill()
			<-p.done
		}
	}
}

func command(name string, args ...string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, name, args...).Run()
}

func value(name string) string {
	b, _ := exec.Command("nvram", "get", name).Output()
	return strings.TrimSpace(string(b))
}

func routerMode() bool {
	mode := value("sw_mode")
	return (mode == "1" || mode == "4") && value("wan_route_x") != "IP_Bridged"
}

func wanReady() bool {
	for _, family := range []string{"-4", "-6"} {
		data, _ := exec.Command("ip", family, "route", "show", "default").Output()
		if strings.HasPrefix(string(data), "default ") {
			return true
		}
	}
	return false
}

// Fetch subscription and core through the WAN resolver even while LAN DNS
// forwards to Mihomo. This avoids depending on the configuration being replaced.
func downloadClient() *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	dialer := &net.Dialer{Timeout: 12 * time.Second}
	file, err := os.Open("/etc/resolv.conf")
	if err == nil {
		var upstreams []string
		scan := bufio.NewScanner(file)
		for scan.Scan() {
			fields := strings.Fields(scan.Text())
			if len(fields) == 2 && fields[0] == "nameserver" {
				ip := net.ParseIP(fields[1])
				if ip != nil && !ip.IsLoopback() {
					upstreams = append(upstreams, net.JoinHostPort(ip.String(), "53"))
				}
			}
		}
		file.Close()
		if len(upstreams) > 0 {
			dialer.Resolver = &net.Resolver{
				PreferGo: true,
				Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
					for _, address := range upstreams {
						c, err := (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, network, address)
						if err == nil {
							return c, nil
						}
					}
					return nil, errors.New("WAN DNS unavailable")
				},
			}
		}
	}
	transport.DialContext = dialer.DialContext
	return &http.Client{
		Timeout:   150 * time.Second,
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if req.URL.Scheme != "https" || len(via) > 5 {
				return errors.New("invalid redirect")
			}
			return nil
		},
	}
}

func fetch(client *http.Client, url string, max int64, target io.Writer) error {
	resp, err := client.Get(url)
	if err != nil {
		return errors.New("HTTPS 下载失败，请检查地址、网络、证书和系统时间")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return errors.New("下载服务器未返回 HTTP 200")
	}
	n, err := io.Copy(target, io.LimitReader(resp.Body, max+1))
	if err != nil || n > max {
		return errors.New("下载不完整或超过大小限制")
	}
	return nil
}

func installCore(client *http.Client, conf proxySettings) (string, error) {
	target := filepath.Join(runDir, "core-"+conf.CoreSHA256)
	if info, err := os.Stat(target); err == nil && info.Mode().IsRegular() {
		return target, nil
	}
	archive, err := os.CreateTemp(runDir, "core-download-*")
	if err != nil {
		return "", err
	}
	defer os.Remove(archive.Name())
	defer archive.Close()
	hash := sha256.New()
	if err := fetch(client, conf.CoreURL, 80<<20, io.MultiWriter(archive, hash)); err != nil {
		return "", err
	}
	if hex.EncodeToString(hash.Sum(nil)) != conf.CoreSHA256 {
		return "", errors.New("Mihomo 核心 SHA-256 不匹配")
	}
	if _, err := archive.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	head := make([]byte, 20)
	if _, err := io.ReadFull(archive, head); err != nil {
		return "", err
	}
	if _, err := archive.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	var data io.Reader = archive
	if head[0] == 0x1f && head[1] == 0x8b {
		z, err := gzip.NewReader(archive)
		if err != nil {
			return "", errors.New("Mihomo gzip 解压失败")
		}
		defer z.Close()
		data = z
		if _, err := io.ReadFull(data, head); err != nil {
			return "", err
		}
	}
	if string(head[:4]) != "\x7fELF" || head[4] != 1 || head[5] != 1 || head[18] != 8 || head[19] != 0 {
		return "", errors.New("核心须为 32 位 MIPS 小端 Linux ELF")
	}
	tmp := target + ".new"
	defer os.Remove(tmp)
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0700)
	if err != nil {
		return "", err
	}
	_, headErr := f.Write(head)
	n, copyErr := io.Copy(f, io.LimitReader(data, 80<<20+1))
	closeErr := f.Close()
	if headErr != nil || copyErr != nil || closeErr != nil || n > 80<<20 {
		return "", errors.New("无法保存 Mihomo 核心")
	}
	return target, os.Rename(tmp, target)
}

var domainPattern = regexp.MustCompile(`^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

func localRules(conf proxySettings) ([]string, error) {
	if len(conf.Allow)+len(conf.Block)+len(conf.Rules) > 3500 {
		return nil, errors.New("本机规则超过 3500 字节")
	}
	var rules []string
	for _, item := range []struct{ domains, target string }{{conf.Allow, "DIRECT"}, {conf.Block, "ADS"}} {
		for _, row := range strings.Split(item.domains, "\n") {
			domain := strings.ToLower(strings.TrimSpace(row))
			if domain == "" {
				continue
			}
			if len(domain) > 253 || !domainPattern.MatchString(domain) {
				return nil, errors.New("广告域名格式有误")
			}
			rules = append(rules, "DOMAIN-SUFFIX,"+domain+","+item.target)
		}
	}
	for _, row := range strings.Split(conf.Rules, "\n") {
		rule := strings.TrimSpace(row)
		if rule == "" {
			continue
		}
		parts := strings.Split(rule, ",")
		if len(parts) < 3 || parts[0] == "MATCH" {
			return nil, errors.New("本机分流规则需包含规则类型、匹配条件和策略")
		}
		rules = append(rules, rule)
	}
	return rules, nil
}

func bypassRules(conf proxySettings) ([]byte, error) {
	var rules strings.Builder
	for _, list := range []struct{ flag, contents string }{
		{"-s", conf.BypassClients}, {"-d", conf.BypassDestinations},
	} {
		items := strings.Fields(list.contents)
		if len(items) > 32 {
			return nil, errors.New("每类最多设置 32 条绕过地址")
		}
		for _, item := range items {
			prefix, err := netip.ParsePrefix(item)
			if err != nil {
				addr, addrErr := netip.ParseAddr(item)
				if addrErr != nil || addr.Zone() != "" {
					return nil, errors.New("绕过地址须为 IPv4、IPv6 地址或 CIDR")
				}
				prefix = netip.PrefixFrom(addr, addr.BitLen())
			}
			if prefix.Bits() == 0 || prefix.Addr().Is4In6() {
				return nil, errors.New("绕过地址须指定设备地址或具体网段")
			}
			family := "-6"
			if prefix.Addr().Is4() {
				family = "-4"
			}
			rules.WriteString(family + " " + list.flag + " " + prefix.Masked().String() + "\n")
		}
	}
	return []byte(rules.String()), nil
}

func prepareConfig(client *http.Client, conf proxySettings, path string) error {
	var body strings.Builder
	if err := fetch(client, conf.ConfigURL, 16<<20, &body); err != nil {
		return err
	}
	var config map[string]json.RawMessage
	if err := json.Unmarshal([]byte(body.String()), &config); err != nil || config == nil {
		return errors.New("订阅地址须返回 Mihomo JSON 配置")
	}
	var dns map[string]json.RawMessage
	if err := json.Unmarshal(config["dns"], &dns); err != nil || dns == nil {
		return errors.New("订阅须包含 DNS 配置")
	}
	var groups []map[string]json.RawMessage
	if err := json.Unmarshal(config["proxy-groups"], &groups); err != nil || len(groups) == 0 {
		return errors.New("订阅须包含代理分组")
	}
	rules, err := localRules(conf)
	if err != nil {
		return err
	}
	var remoteRules []string
	if err := json.Unmarshal(config["rules"], &remoteRules); err != nil || len(remoteRules) == 0 {
		return errors.New("订阅须包含分流规则")
	}
	config["rules"], _ = json.Marshal(append(rules, remoteRules...))
	for _, key := range []string{"port", "socks-port", "mixed-port", "redir-port", "tproxy-port", "external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-ui", "external-ui-url", "interface-name", "routing-mark", "secret", "iptables", "ebpf"} {
		delete(config, key)
	}
	config["ipv6"] = json.RawMessage(`true`)
	config["allow-lan"] = json.RawMessage(`false`)
	config["mode"] = json.RawMessage(`"rule"`)
	config["log-level"] = json.RawMessage(`"error"`)
	config["external-controller"] = json.RawMessage(`"127.0.0.1:17890"`)
	config["tun"] = json.RawMessage(`{"enable":false}`)
	config["listeners"] = json.RawMessage(`[{"name":"r3p-v4","type":"tproxy","listen":"127.0.0.1","port":17891,"udp":true},{"name":"r3p-v6","type":"tproxy","listen":"::1","port":17892,"udp":true}]`)
	if _, ok := config["sniffer"]; !ok {
		config["sniffer"] = json.RawMessage(`{"enable":true,"parse-pure-ip":true,"sniff":{"HTTP":{"ports":[80,"8080-8880"]},"TLS":{"ports":[443,8443]},"QUIC":{"ports":[443,8443]}}}`)
	}
	dns["enable"] = json.RawMessage(`true`)
	dns["listen"] = json.RawMessage(`"127.0.0.1:17853"`)
	dns["ipv6"] = json.RawMessage(`true`)
	dns["enhanced-mode"] = json.RawMessage(`"redir-host"`)
	config["dns"], _ = json.Marshal(dns)
	data, err := json.Marshal(config)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}

var control = &http.Client{Timeout: 2 * time.Second, Transport: &http.Transport{}}

func api(method, path, body string, output any) error {
	req, err := http.NewRequest(method, controlURL+path, strings.NewReader(body))
	if err != nil {
		return err
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := control.Do(req)
	if err != nil {
		return errors.New("Mihomo 控制接口不可用")
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return errors.New("Mihomo 未接受该操作")
	}
	if output != nil {
		return json.NewDecoder(io.LimitReader(resp.Body, 256<<10)).Decode(output)
	}
	return nil
}

type proxyGroup struct {
	Now string   `json:"now"`
	All []string `json:"all"`
}

func proxyGroups() map[string]proxyGroup {
	groups := make(map[string]proxyGroup)
	for _, group := range []string{"PROXY", "ADS", "GOOGLE", "YOUTUBE", "FINAL"} {
		var data proxyGroup
		if api(http.MethodGet, "/proxies/"+group, "", &data) == nil && len(data.All) > 0 {
			groups[group] = data
		}
	}
	return groups
}

func (p *proxyProcess) selectGroup(group, name string) error {
	data, ok := proxyGroups()[group]
	if ok {
		for _, choice := range data.All {
			if name == choice {
				body, _ := json.Marshal(map[string]string{"name": name})
				return api(http.MethodPut, "/proxies/"+group, string(body), nil)
			}
		}
	}
	return errors.New("代理分组或选项无效")
}

func socketPresent(path, address string) bool {
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) > 3 && fields[1] == address && (strings.Contains(path, "udp") || fields[3] == "0A") {
			return true
		}
	}
	return false
}

func proxySockets() bool {
	return socketPresent("/proc/net/tcp", "0100007F:45E3") &&
		socketPresent("/proc/net/udp", "0100007F:45E3") &&
		socketPresent("/proc/net/tcp6", "00000000000000000000000001000000:45E4") &&
		socketPresent("/proc/net/udp6", "00000000000000000000000001000000:45E4") &&
		socketPresent("/proc/net/udp", "0100007F:45BD")
}

func startProxy(core, dir string) (*proxyProcess, error) {
	cmd := exec.Command(core, "-d", dir, "-f", filepath.Join(dir, "config.json"))
	cmd.Env = append(os.Environ(), "GOMEMLIMIT=150MiB", "GOGC=70")
	setParentDeath(cmd)
	log, err := os.OpenFile(filepath.Join(dir, "mihomo.log"), os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
	if err == nil {
		defer log.Close()
		cmd.Stdout = log
		cmd.Stderr = log
	}
	if err := cmd.Start(); err != nil {
		return nil, errors.New("无法运行 MIPS 核心")
	}
	p := &proxyProcess{cmd: cmd, done: make(chan struct{}), dir: dir}
	go func() {
		cmd.Wait()
		close(p.done)
	}()
	for attempts := 0; attempts < 40 && !p.exited(); attempts++ {
		if api(http.MethodGet, "/version", "", nil) == nil && proxySockets() {
			return p, nil
		}
		time.Sleep(250 * time.Millisecond)
	}
	p.stop()
	return nil, errors.New("Mihomo 启动失败，未找到双栈 TCP/UDP 和 DNS 监听")
}

func activateProxy(dir string) error {
	policy, err := os.ReadFile(filepath.Join(dir, "bypass"))
	if err != nil {
		return err
	}
	if err := os.WriteFile(runDir+"/proxy.bypass.new", policy, 0600); err != nil {
		return err
	}
	if err := os.Rename(runDir+"/proxy.bypass.new", runDir+"/proxy.bypass"); err != nil {
		return err
	}
	os.Remove(proxyReady)
	if err := os.WriteFile(proxyMarker, nil, 0600); err != nil {
		return err
	}
	if err := command("/sbin/r3p-net-reload"); err != nil {
		return errors.New("透明代理防火墙或 DNS 初始化失败")
	}
	if _, err := os.Stat(proxyReady); err != nil {
		return errors.New("IPv4 或 IPv6 透明代理规则未成功安装")
	}
	return nil
}

func deactivateProxy() {
	os.Remove(proxyMarker)
	os.Remove(proxyReady)
	os.Remove(runDir + "/proxy.bypass")
	command("/sbin/r3p-net-reload")
}

func (s *service) stopProxy() {
	deactivateProxy()
	if s.proxy != nil {
		s.proxy.stop()
		s.proxy = nil
	}
}

func (s *service) updateProxy(refresh bool) error {
	conf := s.conf.Proxy
	if !refresh && s.proxy != nil {
		return nil
	}
	client := downloadClient()
	defer client.CloseIdleConnections()
	core, err := installCore(client, conf)
	if err != nil {
		return err
	}
	dir, err := os.MkdirTemp(runDir, "config-*")
	if err != nil {
		return err
	}
	keep := false
	defer func() {
		if !keep {
			os.RemoveAll(dir)
		}
	}()
	policy, err := bypassRules(conf)
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "bypass"), policy, 0600); err != nil {
		return err
	}
	path := filepath.Join(dir, "config.json")
	if err := prepareConfig(client, conf, path); err != nil {
		return err
	}
	if err := command(core, "-t", "-d", dir, "-f", path); err != nil {
		return errors.New("Mihomo 配置校验失败")
	}
	if refresh && !conf.Enabled {
		return nil
	}
	old := s.proxy
	defer func() {
		if old != nil && s.proxy == nil {
			os.RemoveAll(old.dir)
		}
	}()
	if old != nil {
		s.stopProxy()
	}
	newProxy, err := startProxy(core, dir)
	if err == nil {
		err = activateProxy(dir)
	}
	if err != nil {
		deactivateProxy()
		if newProxy != nil {
			newProxy.stop()
		}
		if old != nil {
			if restored, oldErr := startProxy(old.cmd.Path, old.dir); oldErr == nil {
				if activateProxy(old.dir) == nil {
					s.proxy = restored
					return errors.New(err.Error() + "，已恢复上一份有效配置")
				}
				deactivateProxy()
				restored.stop()
			}
		}
		return err
	}
	s.proxy = newProxy
	for group, choice := range conf.Selections {
		// Missing choices are expected when a node is removed by the new subscription.
		body, _ := json.Marshal(map[string]string{"name": choice})
		api(http.MethodPut, "/proxies/"+group, string(body), nil)
	}
	keep = true
	if old != nil {
		os.RemoveAll(old.dir)
		if old.cmd.Path != core {
			os.Remove(old.cmd.Path)
		}
	}
	return nil
}
