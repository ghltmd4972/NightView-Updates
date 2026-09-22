//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

const (
	shcneAssocChanged = 0x08000000
	shcnfIDList       = 0x0000
)

var (
	assocShell32        = syscall.NewLazyDLL("shell32.dll")
	assocSHChangeNotify = assocShell32.NewProc("SHChangeNotify")
)

func registerFileAssociations(mainPath string) error {
	installerPath, _ := os.Executable()
	installerName := filepath.Base(installerPath)
	base := "HKCU\\Software\\Classes"
	if err := registerAssociationsAt(base, mainPath, installerName, supportedImageExtensions, "NightView.Image"); err != nil {
		return err
	}
	appPaths := "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\NightView.exe"
	if err := regAddDefault(appPaths, mainPath); err != nil {
		return err
	}
	if err := regAddValue(appPaths, "Path", filepath.Dir(mainPath), "REG_SZ"); err != nil {
		return err
	}
	assocSHChangeNotify.Call(shcneAssocChanged, shcnfIDList, 0, 0)
	return nil
}

func registerAssociationsAt(base, mainPath, installerName string, extensions []string, progID string) error {
	mainPath = filepath.Clean(mainPath)
	command, err := associationOpenCommand(mainPath)
	if err != nil {
		return err
	}
	if strings.TrimSpace(base) == "" || strings.TrimSpace(progID) == "" {
		return fmt.Errorf("invalid association registry namespace")
	}

	progKey := base + "\\" + progID
	if err := regAddDefault(progKey, "NightView Image"); err != nil {
		return err
	}
	if err := regAddDefault(progKey+"\\DefaultIcon", "\""+mainPath+"\",0"); err != nil {
		return err
	}
	if err := regAddDefault(progKey+"\\shell\\open\\command", command); err != nil {
		return err
	}

	appKey := base + "\\Applications\\NightView.exe"
	if err := regAddValue(appKey, "FriendlyAppName", "NightView", "REG_SZ"); err != nil {
		return err
	}
	if err := regAddDefault(appKey+"\\shell\\open\\command", command); err != nil {
		return err
	}

	for _, ext := range extensions {
		ext = strings.ToLower(strings.TrimSpace(ext))
		if len(ext) < 2 || ext[0] != '.' || strings.ContainsAny(ext, "\\/\" ") {
			return fmt.Errorf("invalid image extension: %q", ext)
		}
		if err := regAddDefault(base+"\\"+ext, progID); err != nil {
			return err
		}
		if err := regAddValue(base+"\\"+ext+"\\OpenWithProgids", progID, "", "REG_SZ"); err != nil {
			return err
		}
		if err := regAddValue(appKey+"\\SupportedTypes", ext, "", "REG_SZ"); err != nil {
			return err
		}
	}

	for _, name := range uniqueAssociationAppNames(installerName) {
		aliasKey := base + "\\Applications\\" + name + "\\shell\\open\\command"
		if err := regAddDefault(aliasKey, command); err != nil {
			return err
		}
	}
	return nil
}

func regAddDefault(key, data string) error {
	return runReg("ADD", key, "/ve", "/t", "REG_SZ", "/d", data, "/f")
}

func regAddValue(key, name, data, typ string) error {
	return runReg("ADD", key, "/v", name, "/t", typ, "/d", data, "/f")
}

func runReg(args ...string) error {
	cmd := exec.Command("reg.exe", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(output))
		if len(msg) > 600 {
			msg = msg[:600]
		}
		return fmt.Errorf("레지스트리 등록 실패: reg.exe %s: %v: %s", strings.Join(args, " "), err, msg)
	}
	return nil
}
