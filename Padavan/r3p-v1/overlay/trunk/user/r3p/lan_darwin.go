package main

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

func bindLAN(_, _ string, _ syscall.RawConn) error {
	return errors.New("WebDAV requires the router LAN bridge")
}

func lockService() (*os.File, error) {
	lock, err := os.OpenFile(runDir+"/lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, err
	}
	return lock, nil
}

func setParentDeath(cmd *exec.Cmd) {}
