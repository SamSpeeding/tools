package main

import (
	"bufio"
	"context"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"io/fs"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/net/webdav"
)

type credentials struct {
	User string
	Salt string
	Hash string
}

func (c *credentials) set(user, password string) error {
	if len(user) == 0 || len(user) > 64 || strings.ContainsAny(user, ":\r\n") || len(password) < 8 || len(password) > 128 {
		return errors.New("WebDAV 用户名无效，密码须为 8–128 字节")
	}
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return err
	}
	hash, err := pbkdf2.Key(sha256.New, password, salt, 600000, 32)
	if err != nil {
		return err
	}
	*c = credentials{User: user, Salt: hex.EncodeToString(salt), Hash: hex.EncodeToString(hash)}
	return nil
}

func (c credentials) valid(user, password string) bool {
	if user != c.User || len(password) > 128 {
		return false
	}
	salt, err := hex.DecodeString(c.Salt)
	if err != nil {
		return false
	}
	hash, err := pbkdf2.Key(sha256.New, password, salt, 600000, 32)
	return err == nil && subtle.ConstantTimeCompare([]byte(hex.EncodeToString(hash)), []byte(c.Hash)) == 1
}

type davFS struct{ root *os.Root }

func davPath(name string) string {
	return filepath.Join(".", strings.TrimPrefix(name, "/"))
}

func (d davFS) Mkdir(_ context.Context, name string, perm os.FileMode) error {
	return d.root.Mkdir(davPath(name), perm)
}

func (d davFS) OpenFile(_ context.Context, name string, flag int, perm os.FileMode) (webdav.File, error) {
	return d.root.OpenFile(davPath(name), flag, perm)
}

func (d davFS) RemoveAll(_ context.Context, name string) error {
	path := davPath(name)
	if path == "." {
		return fs.ErrPermission
	}
	return d.root.RemoveAll(path)
}

func (d davFS) Rename(_ context.Context, oldName, newName string) error {
	oldPath, newPath := davPath(oldName), davPath(newName)
	if oldPath == "." || newPath == "." {
		return fs.ErrPermission
	}
	return d.root.Rename(oldPath, newPath)
}

func (d davFS) Stat(_ context.Context, name string) (os.FileInfo, error) {
	return d.root.Stat(davPath(name))
}

func mediaMounts() []string {
	var mounts []string
	file, err := os.Open("/proc/mounts")
	if err != nil {
		return mounts
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 || !strings.HasPrefix(fields[0], "/dev/") {
			continue
		}
		mount := strings.NewReplacer(`\040`, " ", `\011`, "\t", `\134`, `\`).Replace(fields[1])
		if filepath.Dir(mount) == "/media" {
			mounts = append(mounts, mount)
		}
	}
	return mounts
}

func openMediaRoot(path string) (*os.Root, error) {
	for _, mount := range mediaMounts() {
		relative, err := filepath.Rel(mount, path)
		if err != nil || !filepath.IsLocal(relative) {
			continue
		}
		disk, err := os.OpenRoot(mount)
		if err != nil {
			return nil, err
		}
		defer disk.Close()
		return disk.OpenRoot(relative)
	}
	return nil, errors.New("共享目录必须位于已挂载的 USB 磁盘上")
}

type davServer struct {
	http *http.Server
	done chan struct{}
}

func (d *davServer) close() {
	d.http.Close()
	<-d.done
}

func startDAV(conf davSettings) (*davServer, error) {
	root, err := openMediaRoot(conf.Path)
	if err != nil {
		return nil, err
	}
	lan, err := lanAddress()
	if err != nil {
		root.Close()
		return nil, err
	}
	lc := net.ListenConfig{Control: bindLAN}
	listener, err := lc.Listen(context.Background(), "tcp4", net.JoinHostPort(lan, strconv.Itoa(conf.Port)))
	if err != nil {
		root.Close()
		return nil, err
	}
	handler := &webdav.Handler{FileSystem: davFS{root}, LockSystem: webdav.NewMemLS()}
	var authMu sync.Mutex
	var cachedAuth [32]byte
	var expires time.Time
	var nextAttempt time.Time
	var requests sync.RWMutex
	stopping := false
	server := &http.Server{
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    32 << 10,
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			requests.RLock()
			defer requests.RUnlock()
			if stopping {
				http.Error(w, "Service stopping", http.StatusServiceUnavailable)
				return
			}
			header := sha256.Sum256([]byte(r.Header.Get("Authorization")))
			user, password, ok := r.BasicAuth()
			valid := false
			if ok && user == conf.Credentials.User {
				authMu.Lock()
				valid = time.Now().Before(expires) && subtle.ConstantTimeCompare(header[:], cachedAuth[:]) == 1
				if !valid && time.Now().After(nextAttempt) {
					valid = conf.Credentials.valid(user, password)
					nextAttempt = time.Now().Add(time.Second)
					if valid {
						cachedAuth, expires = header, time.Now().Add(2*time.Minute)
					}
				}
				authMu.Unlock()
			}
			if !valid {
				w.Header().Set("WWW-Authenticate", `Basic realm="R3P WebDAV", charset="UTF-8"`)
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			switch r.Method {
			case "GET", "HEAD", "OPTIONS", "PROPFIND":
			default:
				if conf.ReadOnly {
					w.WriteHeader(http.StatusForbidden)
					return
				}
			}
			handler.ServeHTTP(w, r)
		}),
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer root.Close()
		server.Serve(listener)
		requests.Lock()
		stopping = true
		requests.Unlock()
	}()
	return &davServer{http: server, done: done}, nil
}

func lanAddress() (string, error) {
	i, err := net.InterfaceByName("br0")
	if err != nil {
		return "", err
	}
	addresses, err := i.Addrs()
	if err != nil {
		return "", err
	}
	for _, address := range addresses {
		ip, _, err := net.ParseCIDR(address.String())
		if err == nil && ip.To4() != nil {
			return ip.String(), nil
		}
	}
	return "", errors.New("LAN 尚未取得 IPv4 地址")
}
