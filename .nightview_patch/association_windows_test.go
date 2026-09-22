//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestRegisterAssociationsAtWritesViewerAndLegacyInstallerAliases(t *testing.T) {
	suffix := fmt.Sprintf("NightViewAssocTest_%d", time.Now().UnixNano())
	base := "HKCU\\Software\\Classes\\" + suffix
	defer exec.Command("reg.exe", "DELETE", base, "/f").Run()

	target := "C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe"
	if err := registerAssociationsAt(base, target, "NightViewSetup_1.6.1_Fixed.exe", []string{".nvt"}, "NightView.TestImage"); err != nil {
		t.Fatal(err)
	}

	command, err := associationOpenCommand(target)
	if err != nil {
		t.Fatal(err)
	}
	mustRegistryContain(t, base+"\\NightView.TestImage\\shell\\open\\command", command)
	mustRegistryContain(t, base+"\\Applications\\NightView.exe\\shell\\open\\command", command)
	mustRegistryContain(t, base+"\\Applications\\NightViewSetup_1.6.1_Fixed.exe\\shell\\open\\command", command)
	mustRegistryContain(t, base+"\\Applications\\NightViewSetup_1.6.0_Final.exe\\shell\\open\\command", command)
	mustRegistryContain(t, base+"\\.nvt", "NightView.TestImage")
}

func mustRegistryContain(t *testing.T, key, want string) {
	t.Helper()
	out, err := exec.Command("reg.exe", "QUERY", key, "/ve").CombinedOutput()
	if err != nil {
		t.Fatalf("reg query %q: %v\n%s", key, err, out)
	}
	if !strings.Contains(string(out), want) {
		t.Fatalf("registry %q does not contain %q\n%s", key, want, out)
	}
}
