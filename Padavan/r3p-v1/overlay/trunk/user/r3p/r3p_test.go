package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestPrepareConfigPreservesRulesAndAddsDualStackListeners(t *testing.T) {
	const subscription = `{"mixed-port":7890,"ipv6":false,"external-controller":"0.0.0.0:9090",
"tun":{"enable":true},"dns":{"enable":true,"ipv6":false,"nameserver-policy":{"example.com":"https://dns.example/dns-query"}},
"proxy-groups":[{"name":"ADS","type":"select","proxies":["REJECT","DIRECT"]}],
"rule-providers":{"ads":{"type":"inline","payload":["+.ads.example"]}},"rules":["MATCH,DIRECT"]}`
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(subscription))
	}))
	defer server.Close()
	target := filepath.Join(t.TempDir(), "config.json")
	conf := proxySettings{
		ConfigURL: server.URL,
		Allow:     "safe.example",
		Block:     "ads.example",
		Rules:     "DOMAIN-SUFFIX,local.example,DIRECT",
	}
	if err := prepareConfig(server.Client(), conf, target); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	var config struct {
		Rules     []string
		Listeners []struct {
			Listen string
			UDP    bool
		}
		IPv6       bool
		DNS        map[string]json.RawMessage
		Controller string                     `json:"external-controller"`
		MixedPort  int                        `json:"mixed-port"`
		Providers  map[string]json.RawMessage `json:"rule-providers"`
	}
	if err := json.Unmarshal(body, &config); err != nil {
		t.Fatal(err)
	}
	wantRules := []string{"DOMAIN-SUFFIX,safe.example,DIRECT", "DOMAIN-SUFFIX,ads.example,ADS", "DOMAIN-SUFFIX,local.example,DIRECT", "MATCH,DIRECT"}
	if !reflect.DeepEqual(config.Rules, wantRules) || len(config.Providers) != 1 {
		t.Fatalf("incorrect merged rules: %v", config.Rules)
	}
	if !config.IPv6 || len(config.Listeners) != 2 || config.Listeners[0].Listen != "127.0.0.1" ||
		config.Listeners[1].Listen != "::1" || !config.Listeners[0].UDP || !config.Listeners[1].UDP {
		t.Fatalf("incorrect dual-stack listeners: %+v", config)
	}
	if config.Controller != "127.0.0.1:17890" || config.MixedPort != 0 || config.DNS["nameserver-policy"] == nil {
		t.Fatalf("incorrect network configuration: %+v", config)
	}
}

func TestDAVFileSystemCannotEscapeRoot(t *testing.T) {
	base := t.TempDir()
	shared := filepath.Join(base, "share")
	if err := os.Mkdir(shared, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(base, "private"), []byte("private"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../private", filepath.Join(shared, "outside")); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(shared)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	dav := davFS{root}
	if err := dav.RemoveAll(context.Background(), "/"); err == nil {
		t.Fatal("deleting the share root should be rejected")
	}
	for _, name := range []string{"/outside", "/../private"} {
		file, err := dav.OpenFile(context.Background(), name, os.O_RDONLY, 0)
		if err == nil {
			file.Close()
			t.Fatalf("read outside share through %q", name)
		}
	}
}

func TestDAVCredentials(t *testing.T) {
	var c credentials
	if err := c.set("storage", "a separate password"); err != nil {
		t.Fatal(err)
	}
	if !c.valid("storage", "a separate password") || c.valid("admin", "a separate password") || c.valid("storage", "bad password") {
		t.Fatal("incorrect WebDAV credentials validation")
	}
}
