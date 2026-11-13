package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

const (
	runDir       = "/tmp/r3p"
	settingsPath = "/etc/storage/r3p-services.json"
	socketPath   = runDir + "/control.sock"
)

type proxySettings struct {
	Selections                        map[string]string
	Enabled                           bool
	CoreURL, CoreSHA256, ConfigURL    string
	Block, Allow, Rules               string
	BypassClients, BypassDestinations string
}

type davSettings struct {
	Enabled, ReadOnly bool
	Path              string
	Port              int
	Credentials       credentials
}

type settings struct {
	Proxy proxySettings
	DAV   davSettings
}

type status struct {
	Busy, ProxyEnabled, ProxyRunning, CoreConfigured, SubscriptionConfigured bool
	CorePinned                                                               bool
	DAVEnabled, DAVRunning, DAVReadOnly                                      bool
	DAVPath, DAVUser, DAVURL                                                 string
	DAVPort                                                                  int
	Mounts                                                                   []string
	ProxyMessage, DAVMessage                                                 string
	Block, Allow, Rules                                                      string
	BypassClients, BypassDestinations                                        string
	Groups                                                                   map[string]proxyGroup
}

type service struct {
	davMu        sync.Mutex
	conf         settings
	dav          *davServer
	proxy        *proxyProcess
	lastLAN      string
	davRetry     bool
	lastProxyTry time.Time
	wantsDAV     atomic.Bool
	mu           sync.Mutex
	current      status
}

func saveSettings(conf settings) error {
	data, err := json.Marshal(conf)
	if err != nil {
		return err
	}
	path := settingsPath + ".new"
	if err := os.WriteFile(path, data, 0600); err != nil {
		return err
	}
	if err := os.Rename(path, settingsPath); err != nil {
		os.Remove(path)
		return err
	}
	return nil
}

func (s *service) handle(raw string) any {
	form, err := url.ParseQuery(raw)
	if err != nil {
		return map[string]string{"Error": "请求格式错误"}
	}
	action := form.Get("action")
	s.mu.Lock()
	defer s.mu.Unlock()
	if action == "status" {
		value := s.current
		value.Mounts = mediaMounts()
		return value
	}
	if action == "dav-stop" || action == "dav-restart" {
		s.davMu.Lock()
		msg := "存储服务已停止"
		if action == "dav-stop" {
			s.stopDAV()
			s.davRetry = false
			s.wantsDAV.Store(false)
		} else {
			s.wantsDAV.Store(true)
			msg = s.restartDAV()
		}
		s.davMu.Unlock()
		s.updateDAVStatus(msg)
		return map[string]bool{"Accepted": true}
	}
	if s.current.Busy {
		return map[string]string{"Error": "正在处理，请稍后再试"}
	}
	s.current.Busy = true
	go func() {
		msg, isDAV := s.apply(action, form)
		s.publish(msg, isDAV)
	}()
	return map[string]bool{"Accepted": true}
}

func (s *service) publish(msg string, dav bool) {
	var groups map[string]proxyGroup
	if s.proxy != nil {
		groups = proxyGroups()
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	st := &s.current
	if dav {
		st.DAVMessage = msg
	} else {
		st.ProxyMessage = msg
	}
	st.Busy = false
	st.ProxyEnabled, st.ProxyRunning = s.conf.Proxy.Enabled, s.proxy != nil
	st.CoreConfigured = s.conf.Proxy.CoreURL != ""
	st.CorePinned = s.conf.Proxy.CoreSHA256 != ""
	st.SubscriptionConfigured = s.conf.Proxy.ConfigURL != ""
	st.Block, st.Allow, st.Rules = s.conf.Proxy.Block, s.conf.Proxy.Allow, s.conf.Proxy.Rules
	st.BypassClients, st.BypassDestinations = s.conf.Proxy.BypassClients, s.conf.Proxy.BypassDestinations
	st.Groups = groups
	s.updateDAVStatus(st.DAVMessage)
}

func (s *service) updateDAVStatus(message string) {
	s.davMu.Lock()
	defer s.davMu.Unlock()
	st := &s.current
	d := s.conf.DAV
	st.DAVMessage = message
	st.DAVEnabled, st.DAVReadOnly, st.DAVRunning = d.Enabled, d.ReadOnly, s.dav != nil
	st.DAVPath, st.DAVPort, st.DAVUser = d.Path, d.Port, d.Credentials.User
	st.DAVURL = ""
	if s.dav != nil {
		st.DAVURL = "http://" + net.JoinHostPort(s.lastLAN, strconv.Itoa(d.Port)) + "/"
	}
}

func (s *service) recheck() {
	s.mu.Lock()
	if s.current.Busy {
		s.mu.Unlock()
		return
	}
	s.current.Busy = true
	s.mu.Unlock()

	if s.proxy != nil {
		_, readyErr := os.Stat(proxyReady)
		if s.proxy.exited() || !routerMode() || readyErr != nil {
			// A firewall reload can briefly remove the ready file.
			time.Sleep(time.Second)
			_, readyErr = os.Stat(proxyReady)
			if s.proxy.exited() || !routerMode() || readyErr != nil {
				s.stopProxy()
				s.lastProxyTry = time.Now()
				s.publish("透明代理未运行，已恢复直连", false)
				return
			}
		}
	}
	if s.proxy == nil && s.conf.Proxy.Enabled && s.lastProxyTry.IsZero() && routerMode() && wanReady() {
		s.lastProxyTry = time.Now()
		err := s.updateProxy(false)
		if err != nil {
			s.publish(err.Error()+"，可在后台手动重试", false)
			return
		}
		s.publish("双栈代理运行中", false)
		return
	}
	s.davMu.Lock()
	if s.davRetry || s.dav != nil {
		address, _ := lanAddress()
		if address != s.lastLAN {
			msg := s.restartDAV()
			s.davMu.Unlock()
			s.publish(msg, true)
			return
		}
	}
	s.davMu.Unlock()
	s.mu.Lock()
	s.current.Busy = false
	s.mu.Unlock()
}

var sha256Pattern = regexp.MustCompile(`^[a-fA-F0-9]{64}$`)

func validHTTPS(value string) bool {
	u, err := url.Parse(value)
	return err == nil && len(value) <= 1024 && u.Scheme == "https" && u.Hostname() != "" &&
		u.User == nil && u.Fragment == ""
}

func (s *service) apply(action string, form url.Values) (string, bool) {
	conf := s.conf
	switch action {
	case "proxy-save":
		if value := strings.TrimSpace(form.Get("core")); value != "" {
			if !validHTTPS(value) {
				return "核心地址须为 HTTPS URL", false
			}
			if value != conf.Proxy.CoreURL {
				conf.Proxy.CoreSHA256 = ""
			}
			conf.Proxy.CoreURL = value
		}
		if form.Get("clear_sha256") == "1" {
			conf.Proxy.CoreSHA256 = ""
		}
		if value := strings.TrimSpace(form.Get("sha256")); value != "" {
			if !sha256Pattern.MatchString(value) {
				return "SHA-256 须为 64 位十六进制字符", false
			}
			conf.Proxy.CoreSHA256 = strings.ToLower(value)
		}
		if value := strings.TrimSpace(form.Get("subscription")); value != "" {
			if !validHTTPS(value) {
				return "订阅地址须为 HTTPS URL", false
			}
			conf.Proxy.ConfigURL = value
		}
		if err := s.setConfig(conf); err != nil {
			return err.Error(), false
		}
		return "已保存，点击启用或刷新应用", false
	case "rules-save":
		conf.Proxy.Block = strings.TrimSpace(form.Get("block"))
		conf.Proxy.Allow = strings.TrimSpace(form.Get("allow"))
		conf.Proxy.Rules = strings.TrimSpace(form.Get("rules"))
		conf.Proxy.BypassClients = strings.TrimSpace(form.Get("bypass_clients"))
		conf.Proxy.BypassDestinations = strings.TrimSpace(form.Get("bypass_destinations"))
		if _, err := bypassRules(conf.Proxy); err != nil {
			return err.Error(), false
		}
		if _, err := localRules(conf.Proxy); err != nil {
			return err.Error(), false
		}
		if err := s.setConfig(conf); err != nil {
			return err.Error(), false
		}
		return "本机规则已保存，点击刷新配置生效", false
	case "proxy-on", "proxy-refresh":
		if !routerMode() {
			return "AP 模式保持原网络路径，切换为路由模式后可启用代理", false
		}
		if conf.Proxy.CoreURL == "" || conf.Proxy.ConfigURL == "" {
			return "请先保存核心地址和 JSON 订阅地址", false
		}
		s.lastProxyTry = time.Now()
		if err := s.updateProxy(action == "proxy-refresh"); err != nil {
			return err.Error(), false
		}
		if action == "proxy-on" && !conf.Proxy.Enabled {
			conf.Proxy.Enabled = true
			if err := s.setConfig(conf); err != nil {
				s.stopProxy()
				return err.Error(), false
			}
		}
		if s.proxy == nil {
			return "配置已下载并校验，启用后生效", false
		}
		return "双栈代理运行中", false
	case "proxy-off":
		conf.Proxy.Enabled = false
		if err := s.setConfig(conf); err != nil {
			return err.Error(), false
		}
		s.stopProxy()
		return "代理已关闭", false
	case "proxy-select":
		group, name := form.Get("group"), form.Get("name")
		if s.proxy == nil {
			return "请先启用代理", false
		}
		previous := proxyGroups()[group].Now
		if err := s.proxy.selectGroup(group, name); err != nil {
			return err.Error(), false
		}
		choices := make(map[string]string, len(conf.Proxy.Selections)+1)
		for key, selection := range conf.Proxy.Selections {
			choices[key] = selection
		}
		choices[group] = name
		conf.Proxy.Selections = choices
		if err := s.setConfig(conf); err != nil {
			if previous != "" {
				s.proxy.selectGroup(group, previous)
			}
			return err.Error(), false
		}
		return "代理选项已更新", false
	case "dav-save":
		d := &conf.DAV
		d.Enabled, d.ReadOnly = form.Get("enabled") == "1", form.Get("readonly") == "1"
		d.Path = filepath.Clean(form.Get("path"))
		d.Port, _ = strconv.Atoi(form.Get("port"))
		if !d.Enabled && d.Path == "." {
			d.Path = ""
		}
		if d.Port < 1024 || d.Port > 65535 || ((d.Enabled || d.Path != "") && !strings.HasPrefix(d.Path, "/media/")) {
			return "请选择 USB 共享路径，端口须为 1024–65535", true
		}
		user, password := strings.TrimSpace(form.Get("user")), form.Get("password")
		if password != "" {
			if err := d.Credentials.set(user, password); err != nil {
				return err.Error(), true
			}
		} else if user != d.Credentials.User || (d.Enabled && d.Credentials.Hash == "") {
			return "启用或修改 WebDAV 账号时需要设置密码", true
		}
		if err := s.setConfig(conf); err != nil {
			return err.Error(), true
		}
		s.davMu.Lock()
		defer s.davMu.Unlock()
		s.wantsDAV.Store(true)
		return s.restartDAV(), true
	default:
		return "未知操作", false
	}
}

func (s *service) setConfig(conf settings) error {
	if err := saveSettings(conf); err != nil {
		return errors.New("写入本机设置失败")
	}
	// Padavan commits /etc/storage to flash via its storage service.
	if err := command("/sbin/mtd_storage.sh", "save"); err != nil {
		saveSettings(s.conf)
		return errors.New("保存设置到闪存失败")
	}
	s.davMu.Lock()
	s.conf = conf
	s.davMu.Unlock()
	return nil
}

func (s *service) stopDAV() {
	if s.dav != nil {
		s.dav.close()
		s.dav = nil
	}
}

func (s *service) restartDAV() string {
	s.stopDAV()
	s.lastLAN, _ = lanAddress()
	s.davRetry = s.conf.DAV.Enabled
	if !s.conf.DAV.Enabled {
		return "WebDAV 已关闭"
	}
	if !s.wantsDAV.Load() {
		return "等待 USB 存储"
	}
	dav, err := startDAV(s.conf.DAV)
	if err != nil {
		return "WebDAV 启动失败：" + err.Error()
	}
	s.dav = dav
	return "WebDAV 运行中"
}

func (s *service) serve(conn net.Conn) {
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(4 * time.Second))
	r := bufio.NewReaderSize(conn, 8192)
	line, err := r.ReadSlice('\n')
	if err != nil {
		return
	}
	json.NewEncoder(conn).Encode(s.handle(strings.TrimSuffix(string(line), "\n")))
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "local" {
		conn, err := net.DialTimeout("unix", socketPath, time.Second)
		if err != nil {
			os.Exit(1)
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(5 * time.Second))
		fmt.Fprintf(conn, "action=%s\n", url.QueryEscape(os.Args[2]))
		reply, err := bufio.NewReader(conn).ReadString('\n')
		if err != nil || strings.Contains(reply, "\"Error\"") {
			os.Exit(1)
		}
		return
	}
	syscall.Umask(0077)
	if err := os.MkdirAll(runDir, 0700); err != nil {
		panic(err)
	}
	lock, err := lockService()
	if err != nil {
		return
	}
	defer lock.Close()
	os.Remove(socketPath)
	l, err := net.Listen("unix", socketPath)
	if err != nil {
		panic(err)
	}
	defer l.Close()
	s := &service{conf: settings{DAV: davSettings{Port: 8082}}}
	if data, err := os.ReadFile(settingsPath); err == nil {
		json.Unmarshal(data, &s.conf)
	}
	s.wantsDAV.Store(true)
	if _, err := os.Stat(proxyMarker); err == nil {
		deactivateProxy()
	}
	s.publish(s.restartDAV(), true)
	go func() {
		t := time.NewTicker(3 * time.Second)
		defer t.Stop()
		for range t.C {
			s.recheck()
		}
	}()
	done := make(chan os.Signal, 1)
	signal.Notify(done, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-done
		l.Close()
	}()
	for {
		conn, err := l.Accept()
		if err != nil {
			break
		}
		go s.serve(conn)
	}
}
