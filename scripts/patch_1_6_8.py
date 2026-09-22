from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_8.py <source-root>")

root = Path(sys.argv[1])

def read(name):
    return (root / name).read_text(encoding="utf-8")

def write(name, text):
    (root / name).write_text(text, encoding="utf-8", newline="\n")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)

def sub_once(text, pattern, repl, label, flags=0):
    replacement = (lambda _m: repl) if isinstance(repl, str) else repl
    out, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 regex match, found {count}")
    return out

def replace_between_functions(text, start_sig, next_sig, replacement, label):
    start = text.find(start_sig)
    if start < 0:
        raise SystemExit(f"{label}: start signature not found: {start_sig}")
    end = text.find(next_sig, start + len(start_sig))
    if end < 0:
        raise SystemExit(f"{label}: next signature not found: {next_sig}")
    second = text.find(start_sig, start + len(start_sig))
    if second >= 0 and second < end:
        raise SystemExit(f"{label}: start signature is ambiguous")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]

# ---------------------------------------------------------------------------
# Viewer: detect WEBP by file signature, not filename extension.
# This fixes WEBP files saved/downloaded with .png/.jpg names.
# ---------------------------------------------------------------------------
main = read("main_windows.go")

webp_sniffer = r'''func isWebPContent(path string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()

	var header [12]byte
	n, err := f.Read(header[:])
	if n < len(header) {
		return false
	}
	if err != nil && n == 0 {
		return false
	}
	return string(header[0:4]) == "RIFF" && string(header[8:12]) == "WEBP"
}

'''
main = replace_once(
    main,
    'func webPDecodeCacheDir() string {\n',
    webp_sniffer + 'func webPDecodeCacheDir() string {\n',
    "WEBP content sniffer insertion",
)
main = replace_once(
    main,
    '\tif !isSupportedImagePath(path) {\n',
    '\tif !isSupportedImagePath(path) && !isWebPContent(path) {\n',
    "direct open content-aware support check",
)
main = replace_once(
    main,
    '\tif strings.EqualFold(filepath.Ext(path), ".webp") {\n',
    '\tif strings.EqualFold(filepath.Ext(path), ".webp") || isWebPContent(path) {\n',
    "loadImageAsset WEBP content detection",
)
write("main_windows.go", main)

# ---------------------------------------------------------------------------
# Installer association metadata: per-extension ProgIDs and image icons.
# ---------------------------------------------------------------------------
assoc_core = read("installer/association_core.go")
helpers = r'''
func associationProgIDForExtension(base, ext string) string {
	ext = strings.ToLower(strings.TrimSpace(ext))
	ext = strings.TrimPrefix(ext, ".")
	if ext == "" {
		return base
	}
	return base + "." + ext
}

func associationFriendlyTypeForExtension(ext string) string {
	switch strings.ToLower(strings.TrimSpace(ext)) {
	case ".jpg", ".jpeg", ".jpe", ".jfif":
		return "JPEG 이미지"
	case ".png":
		return "PNG 이미지"
	case ".gif":
		return "GIF 이미지"
	case ".bmp", ".dib":
		return "BMP 이미지"
	case ".tif", ".tiff":
		return "TIFF 이미지"
	case ".ico":
		return "ICO 이미지"
	case ".webp":
		return "WEBP 이미지"
	default:
		return "이미지"
	}
}

func associationDefaultIconForExtension(ext string) string {
	switch strings.ToLower(strings.TrimSpace(ext)) {
	case ".png":
		return "%SystemRoot%\\System32\\imageres.dll,-83"
	case ".jpg", ".jpeg", ".jpe", ".jfif":
		return "%SystemRoot%\\System32\\imageres.dll,-72"
	default:
		return "%SystemRoot%\\System32\\shell32.dll,-16823"
	}
}

'''
assoc_core = replace_once(
    assoc_core,
    'func associationOpenCommand(target string) (string, error) {\n',
    helpers + 'func associationOpenCommand(target string) (string, error) {\n',
    "association metadata helpers",
)
write("installer/association_core.go", assoc_core)

assoc_windows = read("installer/association_windows.go")

register_associations = r'''func registerAssociationsAt(base, mainPath, installerName string, extensions []string, progID string) error {
	mainPath = filepath.Clean(mainPath)
	command, err := associationOpenCommand(mainPath)
	if err != nil {
		return err
	}
	if strings.TrimSpace(base) == "" || strings.TrimSpace(progID) == "" {
		return fmt.Errorf("invalid association registry namespace")
	}

	// Keep the legacy shared ProgID working for users whose Windows UserChoice
	// still points to it, but stop branding every image as "NightView Image"
	// and stop showing the NightView executable icon as the file type icon.
	legacyProgKey := base + "\\" + progID
	if err := regAddDefault(legacyProgKey, "이미지"); err != nil {
		return err
	}
	if err := regAddDefaultExpand(legacyProgKey+"\\DefaultIcon", associationDefaultIconForExtension("")); err != nil {
		return err
	}
	if err := regAddDefault(legacyProgKey+"\\shell\\open\\command", command); err != nil {
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

		extProgID := associationProgIDForExtension(progID, ext)
		extProgKey := base + "\\" + extProgID
		if err := regAddDefault(extProgKey, associationFriendlyTypeForExtension(ext)); err != nil {
			return err
		}
		if err := regAddDefaultExpand(extProgKey+"\\DefaultIcon", associationDefaultIconForExtension(ext)); err != nil {
			return err
		}
		if err := regAddDefault(extProgKey+"\\shell\\open\\command", command); err != nil {
			return err
		}

		extKey := base + "\\" + ext
		if err := removeLegacyDefaultIfEquals(extKey, progID); err != nil {
			return err
		}
		if err := regAddValue(extKey+"\\OpenWithProgids", extProgID, "", "REG_SZ"); err != nil {
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
'''
assoc_windows = replace_between_functions(
    assoc_windows,
    "func registerAssociationsAt(",
    "func registerCapabilitiesAt(",
    register_associations,
    "registerAssociationsAt",
)

register_capabilities = r'''func registerCapabilitiesAt(capabilitiesKey, registeredAppsKey, capabilityReference, mainPath string, extensions []string, progID string) error {
	if strings.TrimSpace(capabilitiesKey) == "" || strings.TrimSpace(registeredAppsKey) == "" || strings.TrimSpace(capabilityReference) == "" {
		return fmt.Errorf("invalid capabilities registry namespace")
	}
	if err := regAddValue(capabilitiesKey, "ApplicationName", "NightView", "REG_SZ"); err != nil {
		return err
	}
	if err := regAddValue(capabilitiesKey, "ApplicationDescription", "NightView Image Viewer", "REG_SZ"); err != nil {
		return err
	}
	if err := regAddValue(capabilitiesKey, "ApplicationIcon", "\""+mainPath+"\",0", "REG_SZ"); err != nil {
		return err
	}
	for _, ext := range extensions {
		ext = strings.ToLower(strings.TrimSpace(ext))
		if len(ext) < 2 || ext[0] != '.' || strings.ContainsAny(ext, "\\/\" ") {
			return fmt.Errorf("invalid image extension: %q", ext)
		}
		if err := regAddValue(capabilitiesKey+"\\FileAssociations", ext, associationProgIDForExtension(progID, ext), "REG_SZ"); err != nil {
			return err
		}
	}
	return regAddValue(registeredAppsKey, "NightView", capabilityReference, "REG_SZ")
}
'''
assoc_windows = replace_between_functions(
    assoc_windows,
    "func registerCapabilitiesAt(",
    "func regQueryDefault(",
    register_capabilities,
    "registerCapabilitiesAt",
)

assoc_windows = replace_once(
    assoc_windows,
    'func regAddDefault(key, data string) error {\n',
    'func regAddDefaultExpand(key, data string) error {\n\treturn runReg("ADD", key, "/ve", "/t", "REG_EXPAND_SZ", "/d", data, "/f")\n}\n\nfunc regAddDefault(key, data string) error {\n',
    "installer REG_EXPAND_SZ default helper",
)
write("installer/association_windows.go", assoc_windows)

# ---------------------------------------------------------------------------
# In-app migration v3: immediately fixes existing NightView.Image branding
# and file icons, and registers per-extension ProgIDs for future selections.
# ---------------------------------------------------------------------------
migration = r'''//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

const associationMigrationMarker = "associations-v3.done"

var (
	migrationShell32        = syscall.NewLazyDLL("shell32.dll")
	migrationSHChangeNotify = migrationShell32.NewProc("SHChangeNotify")
)

func migrationAssociationExtensions() []string {
	out := make([]string, 0, len(supportedExtensions))
	for ext := range supportedExtensions {
		out = append(out, ext)
	}
	sort.Strings(out)
	return out
}

func migrationAssociationProgIDForExtension(base, ext string) string {
	ext = strings.ToLower(strings.TrimSpace(ext))
	ext = strings.TrimPrefix(ext, ".")
	if ext == "" {
		return base
	}
	return base + "." + ext
}

func migrationAssociationFriendlyTypeForExtension(ext string) string {
	switch strings.ToLower(strings.TrimSpace(ext)) {
	case ".jpg", ".jpeg", ".jpe", ".jfif":
		return "JPEG 이미지"
	case ".png":
		return "PNG 이미지"
	case ".gif":
		return "GIF 이미지"
	case ".bmp", ".dib":
		return "BMP 이미지"
	case ".tif", ".tiff":
		return "TIFF 이미지"
	case ".ico":
		return "ICO 이미지"
	case ".webp":
		return "WEBP 이미지"
	default:
		return "이미지"
	}
}

func migrationAssociationDefaultIconForExtension(ext string) string {
	switch strings.ToLower(strings.TrimSpace(ext)) {
	case ".png":
		return "%SystemRoot%\\System32\\imageres.dll,-83"
	case ".jpg", ".jpeg", ".jpe", ".jfif":
		return "%SystemRoot%\\System32\\imageres.dll,-72"
	default:
		return "%SystemRoot%\\System32\\shell32.dll,-16823"
	}
}

func associationMigrationMarkerPath() string {
	local := os.Getenv("LOCALAPPDATA")
	if strings.TrimSpace(local) == "" {
		local = filepath.Dir(os.Args[0])
	}
	return filepath.Join(local, "NightView", associationMigrationMarker)
}

func migrateLegacyImageAssociations() error {
	marker := associationMigrationMarkerPath()
	if _, err := os.Stat(marker); err == nil {
		return nil
	}
	mainPath, err := os.Executable()
	if err != nil {
		return err
	}
	mainPath = filepath.Clean(mainPath)
	if err := repairImageAssociationsAt(
		"HKCU\\Software\\Classes",
		"HKCU\\Software\\NightView\\Capabilities",
		"HKCU\\Software\\RegisteredApplications",
		"Software\\NightView\\Capabilities",
		mainPath,
		migrationAssociationExtensions(),
		"NightView.Image",
	); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(marker), 0o755); err != nil {
		return err
	}
	return os.WriteFile(marker, []byte("NightView image association migration v3\\n"), 0o600)
}

func repairImageAssociationsAt(classesBase, capabilitiesKey, registeredAppsKey, capabilityReference, mainPath string, extensions []string, progID string) error {
	command := "\"" + mainPath + "\" \"%1\""
	legacyProgKey := classesBase + "\\" + progID

	// Keep old Windows UserChoice references valid, but remove NightView
	// branding and the EXE icon from the actual image file type.
	if err := migrationRegAddDefault(legacyProgKey, "이미지"); err != nil {
		return err
	}
	if err := migrationRegAddDefaultExpand(legacyProgKey+"\\DefaultIcon", migrationAssociationDefaultIconForExtension("")); err != nil {
		return err
	}
	if err := migrationRegAddDefault(legacyProgKey+"\\shell\\open\\command", command); err != nil {
		return err
	}

	appKey := classesBase + "\\Applications\\NightView.exe"
	if err := migrationRegAddValue(appKey, "FriendlyAppName", "NightView", "REG_SZ"); err != nil {
		return err
	}
	if err := migrationRegAddDefault(appKey+"\\shell\\open\\command", command); err != nil {
		return err
	}

	for _, ext := range extensions {
		ext = strings.ToLower(strings.TrimSpace(ext))
		if len(ext) < 2 || ext[0] != '.' || strings.ContainsAny(ext, "\\/\" ") {
			return fmt.Errorf("invalid image extension: %q", ext)
		}

		extProgID := migrationAssociationProgIDForExtension(progID, ext)
		extProgKey := classesBase + "\\" + extProgID
		if err := migrationRegAddDefault(extProgKey, migrationAssociationFriendlyTypeForExtension(ext)); err != nil {
			return err
		}
		if err := migrationRegAddDefaultExpand(extProgKey+"\\DefaultIcon", migrationAssociationDefaultIconForExtension(ext)); err != nil {
			return err
		}
		if err := migrationRegAddDefault(extProgKey+"\\shell\\open\\command", command); err != nil {
			return err
		}

		extKey := classesBase + "\\" + ext
		if err := migrationRemoveDefaultIfEquals(extKey, progID); err != nil {
			return err
		}
		if err := migrationRegAddValue(extKey+"\\OpenWithProgids", extProgID, "", "REG_SZ"); err != nil {
			return err
		}
		if err := migrationRegAddValue(appKey+"\\SupportedTypes", ext, "", "REG_SZ"); err != nil {
			return err
		}
	}

	if err := migrationRegAddValue(capabilitiesKey, "ApplicationName", "NightView", "REG_SZ"); err != nil {
		return err
	}
	if err := migrationRegAddValue(capabilitiesKey, "ApplicationDescription", "NightView Image Viewer", "REG_SZ"); err != nil {
		return err
	}
	if err := migrationRegAddValue(capabilitiesKey, "ApplicationIcon", "\""+mainPath+"\",0", "REG_SZ"); err != nil {
		return err
	}
	for _, ext := range extensions {
		if err := migrationRegAddValue(capabilitiesKey+"\\FileAssociations", ext, migrationAssociationProgIDForExtension(progID, ext), "REG_SZ"); err != nil {
			return err
		}
	}
	if err := migrationRegAddValue(registeredAppsKey, "NightView", capabilityReference, "REG_SZ"); err != nil {
		return err
	}

	migrationSHChangeNotify.Call(0x08000000, 0, 0, 0)
	return nil
}

func migrationRegQueryDefault(key string) (string, bool, error) {
	cmd := exec.Command("reg.exe", "QUERY", key, "/ve")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := cmd.CombinedOutput()
	if err != nil {
		if _, ok := err.(*exec.ExitError); ok {
			return "", false, nil
		}
		return "", false, err
	}
	for _, line := range strings.Split(string(output), "\n") {
		if idx := strings.Index(line, "REG_SZ"); idx >= 0 {
			return strings.TrimSpace(line[idx+len("REG_SZ"):]), true, nil
		}
		if idx := strings.Index(line, "REG_EXPAND_SZ"); idx >= 0 {
			return strings.TrimSpace(line[idx+len("REG_EXPAND_SZ"):]), true, nil
		}
	}
	return "", false, nil
}

func migrationRemoveDefaultIfEquals(key, expected string) error {
	value, ok, err := migrationRegQueryDefault(key)
	if err != nil || !ok {
		return err
	}
	if !strings.EqualFold(strings.TrimSpace(value), strings.TrimSpace(expected)) {
		return nil
	}
	return migrationRunReg("DELETE", key, "/ve", "/f")
}

func migrationRegAddDefaultExpand(key, data string) error {
	return migrationRunReg("ADD", key, "/ve", "/t", "REG_EXPAND_SZ", "/d", data, "/f")
}

func migrationRegAddDefault(key, data string) error {
	return migrationRunReg("ADD", key, "/ve", "/t", "REG_SZ", "/d", data, "/f")
}

func migrationRegAddValue(key, name, data, typ string) error {
	return migrationRunReg("ADD", key, "/v", name, "/t", typ, "/d", data, "/f")
}

func migrationRunReg(args ...string) error {
	cmd := exec.Command("reg.exe", args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("레지스트리 복구 실패: reg.exe %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(string(output)))
	}
	return nil
}
'''
write("association_migration_windows.go", migration)

# ---------------------------------------------------------------------------
# Regression tests.
# ---------------------------------------------------------------------------
disguised_test = r'''//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWebPContentOpensEvenWhenNamedPNG(t *testing.T) {
	src := filepath.Join("testdata", "tiny.webp")
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	disguised := filepath.Join(t.TempDir(), "downloaded-image.png")
	if err := os.WriteFile(disguised, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if !isWebPContent(disguised) {
		t.Fatal("WEBP signature was not detected inside .png file")
	}
	asset, err := loadImageAsset(disguised)
	if err != nil {
		t.Fatal(err)
	}
	defer asset.dispose()
	if asset.width != 7 || asset.height != 5 {
		t.Fatalf("disguised WEBP dimensions = %dx%d, want 7x5", asset.width, asset.height)
	}
	if asset.tempPath == "" {
		t.Fatal("disguised WEBP did not use WEBP transcode path")
	}
}
'''
write("webp_disguised_windows_test.go", disguised_test)

assoc_meta_test = r'''//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestAssociationMetadataUsesImageTypesInsteadOfNightViewBranding(t *testing.T) {
	if got := associationFriendlyTypeForExtension(".png"); got != "PNG 이미지" {
		t.Fatalf("png type = %q", got)
	}
	if got := associationFriendlyTypeForExtension(".jpg"); got != "JPEG 이미지" {
		t.Fatalf("jpg type = %q", got)
	}
	if got := associationProgIDForExtension("NightView.Image", ".png"); got != "NightView.Image.png" {
		t.Fatalf("png progID = %q", got)
	}
	if icon := associationDefaultIconForExtension(".png"); !strings.Contains(strings.ToLower(icon), "imageres.dll,-83") {
		t.Fatalf("png icon = %q", icon)
	}
	if icon := associationDefaultIconForExtension(".jpg"); !strings.Contains(strings.ToLower(icon), "imageres.dll,-72") {
		t.Fatalf("jpg icon = %q", icon)
	}
	if icon := associationDefaultIconForExtension(".gif"); strings.Contains(strings.ToLower(icon), "nightview") {
		t.Fatalf("generic image icon unexpectedly points at NightView: %q", icon)
	}
}

func TestRegisterAssociationsAtCreatesPerExtensionImageProgIDs(t *testing.T) {
	suffix := fmt.Sprintf("NightViewAssocMeta_%d", time.Now().UnixNano())
	base := "HKCU\\Software\\Classes\\" + suffix
	defer exec.Command("reg.exe", "DELETE", base, "/f").Run()

	target := "C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe"
	if err := registerAssociationsAt(base, target, "NightViewSetup.exe", []string{".png", ".jpg"}, "NightView.Image"); err != nil {
		t.Fatal(err)
	}

	pngType, ok, err := regQueryDefault(base + "\\NightView.Image.png")
	if err != nil || !ok || pngType != "PNG 이미지" {
		t.Fatalf("png type=%q ok=%v err=%v", pngType, ok, err)
	}
	jpgType, ok, err := regQueryDefault(base + "\\NightView.Image.jpg")
	if err != nil || !ok || jpgType != "JPEG 이미지" {
		t.Fatalf("jpg type=%q ok=%v err=%v", jpgType, ok, err)
	}

	legacyType, ok, err := regQueryDefault(base + "\\NightView.Image")
	if err != nil || !ok || legacyType != "이미지" {
		t.Fatalf("legacy type=%q ok=%v err=%v", legacyType, ok, err)
	}

	out, err := exec.Command("reg.exe", "QUERY", base+"\\NightView.Image.png\\DefaultIcon", "/ve").CombinedOutput()
	if err != nil {
		t.Fatalf("query png icon: %v\n%s", err, out)
	}
	if strings.Contains(strings.ToLower(string(out)), "nightview.exe") || !strings.Contains(strings.ToLower(string(out)), "imageres.dll,-83") {
		t.Fatalf("png icon is not the Windows image icon:\n%s", out)
	}
}
'''
write("installer/association_type_windows_test.go", assoc_meta_test)

print("NightView 1.6.8 patch applied.")
