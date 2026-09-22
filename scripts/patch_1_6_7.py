from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_7.py <source-root>")

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

# ---------------------------------------------------------------------------
# Viewer/core format support: add real WEBP decoding and make BMP/TIFF
# dimension probing use registered Go decoders too.
# ---------------------------------------------------------------------------
core = read("core.go")
core = replace_once(
    core,
    '\t_ "image/png"\n',
    '\t_ "image/png"\n\n\t_ "golang.org/x/image/bmp"\n\t_ "golang.org/x/image/tiff"\n\t_ "golang.org/x/image/webp"\n',
    "core image decoder imports",
)
core = replace_once(
    core,
    '\t".tif": {}, ".tiff": {}, ".ico": {},\n',
    '\t".tif": {}, ".tiff": {}, ".ico": {}, ".webp": {},\n',
    "core supported extensions",
)
write("core.go", core)

main = read("main_windows.go")
main = replace_once(
    main,
    'import (\n\t"fmt"\n',
    'import (\n\t"fmt"\n\t"image/png"\n',
    "main png import",
)
main = replace_once(
    main,
    '\t"unsafe"\n)',
    '\t"unsafe"\n\n\t"golang.org/x/image/webp"\n)',
    "main webp import",
)
main = replace_once(
    main,
    '\tpath            string\n\tframeDimension  GUID\n',
    '\tpath            string\n\ttempPath        string\n\tframeDimension  GUID\n',
    "imageAsset tempPath",
)
old_filter = 'filter := utf16Multi("이미지 파일 (*.jpg;*.jpeg;*.png;*.gif;*.bmp;*.tif;*.tiff;*.ico)\\x00*.jpg;*.jpeg;*.jpe;*.jfif;*.png;*.gif;*.bmp;*.dib;*.tif;*.tiff;*.ico\\x00모든 파일 (*.*)\\x00*.*\\x00\\x00")'
new_filter = 'filter := utf16Multi("이미지 파일 (*.jpg;*.jpeg;*.png;*.gif;*.bmp;*.tif;*.tiff;*.ico;*.webp)\\x00*.jpg;*.jpeg;*.jpe;*.jfif;*.png;*.gif;*.bmp;*.dib;*.tif;*.tiff;*.ico;*.webp\\x00모든 파일 (*.*)\\x00*.*\\x00\\x00")'
main = replace_once(main, old_filter, new_filter, "open dialog filter")
main = replace_once(
    main,
    'messageBox(a.hwnd, "지원하지 않는 이미지 형식입니다.\\n\\n지원: JPG, PNG, GIF, BMP, TIFF, ICO", "NightView", MB_OK|MB_ICONERROR)',
    'messageBox(a.hwnd, "지원하지 않는 이미지 형식입니다.\\n\\n지원: JPG/JPEG, PNG, GIF, BMP/DIB, TIFF, ICO, WEBP", "NightView", MB_OK|MB_ICONERROR)',
    "unsupported format message",
)

load_func = r'''func webPDecodeCacheDir() string {
	base, err := os.UserCacheDir()
	if err != nil || strings.TrimSpace(base) == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "NightView", "decoded")
}

func transcodeWebPToTempPNG(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	img, err := webp.Decode(f)
	_ = f.Close()
	if err != nil {
		return "", fmt.Errorf("WEBP 디코딩 실패: %w", err)
	}

	dir := webPDecodeCacheDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	out, err := os.CreateTemp(dir, "nightview-webp-*.png")
	if err != nil {
		return "", err
	}
	tempPath := out.Name()
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(tempPath)
		}
	}()
	if err := png.Encode(out, img); err != nil {
		return "", fmt.Errorf("WEBP 임시 PNG 변환 실패: %w", err)
	}
	if err := out.Sync(); err != nil {
		return "", err
	}
	if err := out.Close(); err != nil {
		return "", err
	}
	ok = true
	return tempPath, nil
}

func loadImageAsset(path string) (*imageAsset, error) {
	displayPath := path
	tempPath := ""
	if strings.EqualFold(filepath.Ext(path), ".webp") {
		var err error
		tempPath, err = transcodeWebPToTempPNG(path)
		if err != nil {
			return nil, fmt.Errorf("%s (%w)", filepath.Base(path), err)
		}
		displayPath = tempPath
	}
	cleanupTemp := tempPath != ""
	defer func() {
		if cleanupTemp {
			_ = os.Remove(tempPath)
		}
	}()

	p, err := syscall.UTF16PtrFromString(displayPath)
	if err != nil {
		return nil, err
	}
	var img uintptr
	st, _, _ := pGdipLoadImageFromFile.Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&img)))
	if st != 0 || img == 0 {
		return nil, fmt.Errorf("%s (%s)", filepath.Base(path), gdipStatusText(st))
	}
	asset := &imageAsset{handle: img, path: path, tempPath: tempPath}
	ok := false
	defer func() {
		if !ok {
			asset.dispose()
		}
	}()
	asset.exifOrientation = applyExifOrientation(img)
	var w, h uint32
	if s, _, _ := pGdipGetImageWidth.Call(img, uintptr(unsafe.Pointer(&w))); s != 0 {
		return nil, fmt.Errorf("폭을 읽지 못했습니다: %s", gdipStatusText(s))
	}
	if s, _, _ := pGdipGetImageHeight.Call(img, uintptr(unsafe.Pointer(&h))); s != 0 {
		return nil, fmt.Errorf("높이를 읽지 못했습니다: %s", gdipStatusText(s))
	}
	if w == 0 || h == 0 {
		return nil, fmt.Errorf("이미지 크기가 올바르지 않습니다")
	}
	asset.width, asset.height = w, h
	if info, e := os.Stat(path); e == nil {
		asset.fileSize = info.Size()
	}
	readAnimationInfo(asset)
	ok = true
	cleanupTemp = false
	return asset, nil
}
'''
main = sub_once(
    main,
    r'(?ms)^func loadImageAsset\(path string\) \(\*imageAsset, error\) \{.*?^func applyExifOrientation',
    load_func + '\nfunc applyExifOrientation',
    "loadImageAsset function",
)
main = sub_once(
    main,
    r'(?ms)^func \(i \*imageAsset\) dispose\(\) \{.*?^\}',
    r'''func (i *imageAsset) dispose() {
	if i == nil {
		return
	}
	if i.handle != 0 {
		pGdipDisposeImage.Call(i.handle)
		i.handle = 0
	}
	if i.tempPath != "" {
		_ = os.Remove(i.tempPath)
		i.tempPath = ""
	}
}''',
    "imageAsset dispose",
)
main = replace_once(
    main,
    '\tapp.toggleFullscreen()\n\tif startup.HandshakePath != "" {\n',
    '\tapp.toggleFullscreen()\n\tif err := migrateLegacyImageAssociations(); err != nil {\n\t\tmessageBox(hwnd, "Windows 이미지 파일 연결을 안전한 방식으로 복구하지 못했습니다.\\n\\n"+err.Error(), "NightView", MB_OK|MB_ICONERROR)\n\t}\n\tif startup.HandshakePath != "" {\n',
    "startup association migration call",
)
write("main_windows.go", main)

# ---------------------------------------------------------------------------
# Installer support list.
# ---------------------------------------------------------------------------
assoc_core = read("installer/association_core.go")
assoc_core = replace_once(
    assoc_core,
    '\t".ico",\n',
    '\t".ico", ".webp",\n',
    "installer supported extensions",
)
write("installer/association_core.go", assoc_core)

# ---------------------------------------------------------------------------
# Safe Windows associations. Do NOT replace .jpg/.png/etc default ProgID.
# Keep Windows' own file-type/thumbnail registration intact; only advertise
# NightView through OpenWith + RegisteredApplications/Capabilities.
# ---------------------------------------------------------------------------
assoc_windows = read("installer/association_windows.go")
assoc_windows = replace_once(
    assoc_windows,
    '''\tif err := registerAssociationsAt(base, mainPath, installerName, supportedImageExtensions, "NightView.Image"); err != nil {
\t\treturn err
\t}
''',
    '''\tif err := registerAssociationsAt(base, mainPath, installerName, supportedImageExtensions, "NightView.Image"); err != nil {
\t\treturn err
\t}
\tif err := registerCapabilitiesAt(
\t\t"HKCU\\\\Software\\\\NightView\\\\Capabilities",
\t\t"HKCU\\\\Software\\\\RegisteredApplications",
\t\t"Software\\\\NightView\\\\Capabilities",
\t\tmainPath,
\t\tsupportedImageExtensions,
\t\t"NightView.Image",
\t); err != nil {
\t\treturn err
\t}
''',
    "register capabilities call",
)
assoc_windows = replace_once(
    assoc_windows,
    '''\tif err := regAddDefault(progKey+"\\\\DefaultIcon", "\\""+mainPath+"\\",0"); err != nil {
\t\treturn err
\t}
''',
    '''\t// Older NightView builds attached one app icon to every image ProgID.
\t// Remove only NightView's own icon override so Explorer can keep using its
\t// native image/thumbnail presentation.
\t_ = regDeleteKeyIfExists(progKey + "\\\\DefaultIcon")
''',
    "remove NightView DefaultIcon",
)
assoc_windows = replace_once(
    assoc_windows,
    '''\t\tif err := regAddDefault(base+"\\\\"+ext, progID); err != nil {
\t\t\treturn err
\t\t}
\t\tif err := regAddValue(base+"\\\\"+ext+"\\\\OpenWithProgids", progID, "", "REG_SZ"); err != nil {
''',
    '''\t\textKey := base + "\\\\" + ext
\t\tif err := removeLegacyDefaultIfEquals(extKey, progID); err != nil {
\t\t\treturn err
\t\t}
\t\tif err := regAddValue(extKey+"\\\\OpenWithProgids", progID, "", "REG_SZ"); err != nil {
''',
    "stop overwriting extension ProgID",
)
insert_before = '\nfunc regAddDefault(key, data string) error {\n'
helpers = r'''
func registerCapabilitiesAt(capabilitiesKey, registeredAppsKey, capabilityReference, mainPath string, extensions []string, progID string) error {
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
		if err := regAddValue(capabilitiesKey+"\\FileAssociations", ext, progID, "REG_SZ"); err != nil {
			return err
		}
	}
	return regAddValue(registeredAppsKey, "NightView", capabilityReference, "REG_SZ")
}

func regQueryDefault(key string) (string, bool, error) {
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
	}
	return "", false, nil
}

func removeLegacyDefaultIfEquals(key, expected string) error {
	value, ok, err := regQueryDefault(key)
	if err != nil || !ok {
		return err
	}
	if !strings.EqualFold(strings.TrimSpace(value), strings.TrimSpace(expected)) {
		return nil
	}
	return runReg("DELETE", key, "/ve", "/f")
}

func regDeleteKeyIfExists(key string) error {
	cmd := exec.Command("reg.exe", "QUERY", key)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Run(); err != nil {
		if _, ok := err.(*exec.ExitError); ok {
			return nil
		}
		return err
	}
	return runReg("DELETE", key, "/f")
}
'''
assoc_windows = replace_once(
    assoc_windows,
    insert_before,
    '\n' + helpers + insert_before,
    "association helper insertion",
)
write("installer/association_windows.go", assoc_windows)

installer_main = read("installer/main_windows.go")
installer_main = replace_once(
    installer_main,
    '"NightView "+installerVersion+" 설치가 완료되었습니다.\\n\\nJPG, PNG, GIF, BMP, TIFF, ICO 이미지 파일 연결도 NightView로 등록했습니다.\\n앞으로 새 버전은 NightView 안에서 확인하고 자동으로 교체·재시작합니다.\\n\\n설치 위치:\\n"+installDir',
    '"NightView "+installerVersion+" 설치가 완료되었습니다.\\n\\nJPG, PNG, GIF, BMP, TIFF, ICO, WEBP를 NightView 연결 프로그램으로 등록했습니다.\\nWindows의 기존 이미지 형식/썸네일 등록은 그대로 유지합니다.\\n앞으로 새 버전은 NightView 안에서 확인하고 자동으로 교체·재시작합니다.\\n\\n설치 위치:\\n"+installDir',
    "installer completion message",
)
write("installer/main_windows.go", installer_main)

# ---------------------------------------------------------------------------
# One-time migration executed by the updated NightView itself, so users who
# use the in-app updater do not need to reinstall just to repair Explorer.
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

const associationMigrationMarker = "associations-v2.done"

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
	return os.WriteFile(marker, []byte("NightView safe image association migration v2\n"), 0o600)
}

func repairImageAssociationsAt(classesBase, capabilitiesKey, registeredAppsKey, capabilityReference, mainPath string, extensions []string, progID string) error {
	command := "\"" + mainPath + "\" \"%1\""
	progKey := classesBase + "\\" + progID

	if err := migrationRegAddDefault(progKey, "NightView Image"); err != nil {
		return err
	}
	_ = migrationRegDeleteKeyIfExists(progKey + "\\DefaultIcon")
	if err := migrationRegAddDefault(progKey+"\\shell\\open\\command", command); err != nil {
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
		extKey := classesBase + "\\" + ext
		if err := migrationRemoveDefaultIfEquals(extKey, progID); err != nil {
			return err
		}
		if err := migrationRegAddValue(extKey+"\\OpenWithProgids", progID, "", "REG_SZ"); err != nil {
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
		if err := migrationRegAddValue(capabilitiesKey+"\\FileAssociations", ext, progID, "REG_SZ"); err != nil {
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

func migrationRegDeleteKeyIfExists(key string) error {
	cmd := exec.Command("reg.exe", "QUERY", key)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Run(); err != nil {
		if _, ok := err.(*exec.ExitError); ok {
			return nil
		}
		return err
	}
	return migrationRunReg("DELETE", key, "/f")
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
# Tests: real WEBP fixture is generated by the workflow before go test.
# ---------------------------------------------------------------------------
webp_core_test = r'''package main

import (
	"path/filepath"
	"testing"
)

func TestWebPIsSupportedAndDimensionsReadable(t *testing.T) {
	path := filepath.Join("testdata", "tiny.webp")
	if !isSupportedImagePath(path) {
		t.Fatal("WEBP path is not recognized as a supported image")
	}
	w, h, ok := readImageDimensions(path)
	if !ok {
		t.Fatal("WEBP dimensions could not be decoded")
	}
	if w != 7 || h != 5 {
		t.Fatalf("WEBP dimensions = %dx%d, want 7x5", w, h)
	}
}
'''
write("webp_core_test.go", webp_core_test)

webp_windows_test = r'''//go:build windows

package main

import (
	"image"
	"os"
	"path/filepath"
	"testing"
)

func TestWebPTranscodesToReadablePNGAndCleansUp(t *testing.T) {
	source := filepath.Join("testdata", "tiny.webp")
	temp, err := transcodeWebPToTempPNG(source)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(temp)
	if err != nil {
		t.Fatal(err)
	}
	cfg, format, err := image.DecodeConfig(f)
	_ = f.Close()
	if err != nil {
		t.Fatal(err)
	}
	if format != "png" || cfg.Width != 7 || cfg.Height != 5 {
		t.Fatalf("transcoded WEBP = format %q, %dx%d", format, cfg.Width, cfg.Height)
	}

	asset := &imageAsset{tempPath: temp}
	asset.dispose()
	if _, err := os.Stat(temp); !os.IsNotExist(err) {
		t.Fatalf("WEBP temporary PNG was not removed: %v", err)
	}
}
'''
write("webp_windows_test.go", webp_windows_test)

migration_test = r'''//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestRepairImageAssociationsPreservesForeignDefaultsAndRemovesLegacyNightViewDefault(t *testing.T) {
	suffix := fmt.Sprintf("NightViewMigrationTest_%d", time.Now().UnixNano())
	base := "HKCU\\Software\\Classes\\" + suffix
	defer exec.Command("reg.exe", "DELETE", base, "/f").Run()

	classes := base + "\\Classes"
	capabilities := base + "\\Capabilities"
	registered := base + "\\RegisteredApplications"
	foreignKey := classes + "\\.foreign"
	legacyKey := classes + "\\.legacy"

	if err := migrationRegAddDefault(foreignKey, "Existing.Image.Handler"); err != nil {
		t.Fatal(err)
	}
	if err := migrationRegAddDefault(legacyKey, "NightView.Image"); err != nil {
		t.Fatal(err)
	}

	target := "C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe"
	if err := repairImageAssociationsAt(
		classes,
		capabilities,
		registered,
		"Software\\NightView\\Capabilities",
		target,
		[]string{".foreign", ".legacy", ".webp"},
		"NightView.Image",
	); err != nil {
		t.Fatal(err)
	}

	value, ok, err := migrationRegQueryDefault(foreignKey)
	if err != nil || !ok || value != "Existing.Image.Handler" {
		t.Fatalf("foreign default changed: value=%q ok=%v err=%v", value, ok, err)
	}
	if value, ok, err := migrationRegQueryDefault(legacyKey); err != nil || ok {
		t.Fatalf("legacy NightView default was not removed: value=%q ok=%v err=%v", value, ok, err)
	}

	mustRegContains(t, legacyKey+"\\OpenWithProgids", "NightView.Image")
	mustRegContains(t, classes+"\\Applications\\NightView.exe\\SupportedTypes", ".webp")
	mustRegContains(t, capabilities+"\\FileAssociations", "NightView.Image")
	mustRegContains(t, registered, "Software\\NightView\\Capabilities")
}

func mustRegContains(t *testing.T, key, want string) {
	t.Helper()
	out, err := exec.Command("reg.exe", "QUERY", key).CombinedOutput()
	if err != nil {
		t.Fatalf("reg query %q: %v\n%s", key, err, out)
	}
	if !strings.Contains(string(out), want) {
		t.Fatalf("registry %q does not contain %q\n%s", key, want, out)
	}
}
'''
write("association_migration_windows_test.go", migration_test)

# Replace installer's old test that explicitly expected extension default hijacking.
installer_test = read("installer/association_windows_test.go")
installer_test = sub_once(
    installer_test,
    r'(?ms)^func TestRegisterAssociationsAtWritesViewerAndLegacyInstallerAliases\(t \*testing\.T\) \{.*?^\}\n',
    r'''func TestRegisterAssociationsAtPreservesExtensionDefaultAndWritesOpenWith(t *testing.T) {
	suffix := fmt.Sprintf("NightViewAssocTest_%d", time.Now().UnixNano())
	base := "HKCU\\Software\\Classes\\" + suffix
	defer exec.Command("reg.exe", "DELETE", base, "/f").Run()

	target := "C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe"
	extKey := base + "\\.nvt"
	if err := regAddDefault(extKey, "Existing.Image.Handler"); err != nil {
		t.Fatal(err)
	}

	if err := registerAssociationsAt(base, target, "NightViewSetup_1.6.7.exe", []string{".nvt"}, "NightView.TestImage"); err != nil {
		t.Fatal(err)
	}

	command, err := associationOpenCommand(target)
	if err != nil {
		t.Fatal(err)
	}
	mustRegistryContain(t, base+"\\NightView.TestImage\\shell\\open\\command", command)
	mustRegistryContain(t, base+"\\Applications\\NightView.exe\\shell\\open\\command", command)
	mustRegistryContain(t, extKey+"\\OpenWithProgids", "NightView.TestImage")

	value, ok, err := regQueryDefault(extKey)
	if err != nil || !ok || value != "Existing.Image.Handler" {
		t.Fatalf("existing extension default was changed: value=%q ok=%v err=%v", value, ok, err)
	}
}

func TestRegisterAssociationsAtRemovesOnlyLegacyNightViewDefault(t *testing.T) {
	suffix := fmt.Sprintf("NightViewAssocLegacyTest_%d", time.Now().UnixNano())
	base := "HKCU\\Software\\Classes\\" + suffix
	defer exec.Command("reg.exe", "DELETE", base, "/f").Run()

	target := "C:\\Users\\Test User\\AppData\\Local\\NightView\\NightView.exe"
	extKey := base + "\\.nvt"
	if err := regAddDefault(extKey, "NightView.TestImage"); err != nil {
		t.Fatal(err)
	}
	if err := registerAssociationsAt(base, target, "NightViewSetup_1.6.7.exe", []string{".nvt"}, "NightView.TestImage"); err != nil {
		t.Fatal(err)
	}
	if value, ok, err := regQueryDefault(extKey); err != nil || ok {
		t.Fatalf("legacy NightView extension default was not removed: value=%q ok=%v err=%v", value, ok, err)
	}
	mustRegistryContain(t, extKey+"\\OpenWithProgids", "NightView.TestImage")
}

''',
    "installer association test replacement",
    flags=re.M | re.S,
)
write("installer/association_windows_test.go", installer_test)

print("NightView 1.6.7 format/association patch applied.")
