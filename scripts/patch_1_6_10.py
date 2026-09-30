from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_10.py <source-root>")

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

# Replace the old "Explorer-like filename comparator" implementation with
# exact ordering copied from the currently open Explorer view of the folder.
win = r'''//go:build windows

package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var (
	explorerSortShlwapi        = syscall.NewLazyDLL("shlwapi.dll")
	explorerSortStrCmpLogicalW = explorerSortShlwapi.NewProc("StrCmpLogicalW")
)

var errMatchingExplorerViewNotFound = errors.New("matching Windows Explorer view not found")

const explorerViewOrderPowerShell = `$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$want = [System.IO.Path]::GetFullPath($env:NIGHTVIEW_EXPLORER_FOLDER).TrimEnd('\')
$shell = New-Object -ComObject Shell.Application
$found = $false
foreach ($w in @($shell.Windows())) {
    try {
        $loc = [System.IO.Path]::GetFullPath([string]$w.Document.Folder.Self.Path).TrimEnd('\')
        if ([string]::Equals($loc, $want, [System.StringComparison]::OrdinalIgnoreCase)) {
            $found = $true
            foreach ($item in @($w.Document.Folder.Items())) {
                if (-not $item.IsFolder) {
                    $path = [string]$item.Path
                    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($path))
                }
            }
            break
        }
    } catch {}
}
if (-not $found) { exit 3 }
`

func explorerLogicalCompare(a, b string) int {
	ap, errA := syscall.UTF16PtrFromString(a)
	bp, errB := syscall.UTF16PtrFromString(b)
	if errA != nil || errB != nil {
		al, bl := strings.ToLower(a), strings.ToLower(b)
		if al < bl {
			return -1
		}
		if al > bl {
			return 1
		}
		return 0
	}
	r, _, _ := explorerSortStrCmpLogicalW.Call(
		uintptr(unsafe.Pointer(ap)),
		uintptr(unsafe.Pointer(bp)),
	)
	return int(int32(r))
}

func explorerLogicalLess(a, b string) bool {
	return explorerLogicalCompare(a, b) < 0
}

func queryOpenExplorerViewOrder(folder string) ([]string, error) {
	folder = filepath.Clean(folder)
	if folder == "" || folder == "." {
		return nil, errMatchingExplorerViewNotFound
	}

	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()

	cmd := exec.CommandContext(
		ctx,
		"powershell.exe",
		"-NoLogo",
		"-NoProfile",
		"-NonInteractive",
		"-ExecutionPolicy",
		"Bypass",
		"-Command",
		explorerViewOrderPowerShell,
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	cmd.Env = append(os.Environ(), "NIGHTVIEW_EXPLORER_FOLDER="+folder)

	out, err := cmd.Output()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) && exitErr.ExitCode() == 3 {
			return nil, errMatchingExplorerViewNotFound
		}
		return nil, err
	}

	ordered := make([]string, 0, 64)
	scanner := bufio.NewScanner(strings.NewReader(string(out)))
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		decoded, err := base64.StdEncoding.DecodeString(line)
		if err != nil {
			continue
		}
		path := filepath.Clean(string(decoded))
		if path != "" && path != "." {
			ordered = append(ordered, path)
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(ordered) == 0 {
		return nil, errMatchingExplorerViewNotFound
	}
	return ordered, nil
}

func explorerPathKey(path string) string {
	return strings.ToLower(filepath.Clean(path))
}

func reorderFilesByExplorerView(files []string, explorerOrder []string) int {
	if len(files) == 0 || len(explorerOrder) == 0 {
		return 0
	}

	available := make(map[string]string, len(files))
	for _, path := range files {
		available[explorerPathKey(path)] = path
	}

	out := make([]string, 0, len(files))
	used := make(map[string]struct{}, len(files))
	matched := 0
	for _, path := range explorerOrder {
		key := explorerPathKey(path)
		if original, ok := available[key]; ok {
			if _, duplicate := used[key]; duplicate {
				continue
			}
			out = append(out, original)
			used[key] = struct{}{}
			matched++
		}
	}

	// Keep any supported NightView file that Explorer did not enumerate.
	// This is mainly for transient/misnamed files; it must not disturb the
	// relative order copied from Explorer.
	for _, path := range files {
		key := explorerPathKey(path)
		if _, ok := used[key]; ok {
			continue
		}
		out = append(out, path)
		used[key] = struct{}{}
	}

	copy(files, out)
	return matched
}

func sortImagePathsLikeOpenExplorer(files []string, folder string) bool {
	ordered, err := queryOpenExplorerViewOrder(folder)
	if err != nil {
		return false
	}
	return reorderFilesByExplorerView(files, ordered) > 0
}
'''
write("explorer_sort_windows.go", win)

# Non-Windows keeps a deterministic fallback for cross-platform tests.
other = r'''//go:build !windows

package main

func explorerLogicalLess(a, b string) bool {
	return naturalLess(a, b)
}

func sortImagePathsLikeOpenExplorer(files []string, folder string) bool {
	return false
}
'''
write("explorer_sort_other.go", other)

# Integrate exact Explorer view order into every folder-list construction path.
main = read("main_windows.go")

apply_old = '''func (a *viewerApp) applySortMode(sortMode string) {
	if _, ok := validSortModes[sortMode]; !ok {
		sortMode = SortNameAsc
	}
	a.settings.SortMode = sortMode
	_ = saveSettingsFile(a.settingsPath, a.settings)

	if len(a.files) == 0 {
		a.invalidate()
		return
	}

	current := a.currentPath
	if idx := sortImagePathsKeepingCurrent(a.files, sortMode, current); idx >= 0 {
		a.currentIndex = idx
	}
	a.invalidate()
}
'''
apply_new = '''func (a *viewerApp) applySortMode(sortMode string) {
	if _, ok := validSortModes[sortMode]; !ok {
		sortMode = SortNameAsc
	}

	if len(a.files) == 0 {
		a.settings.SortMode = sortMode
		_ = saveSettingsFile(a.settingsPath, a.settings)
		a.invalidate()
		return
	}

	current := a.currentPath
	if sortMode == SortExplorer {
		folder := ""
		if current != "" {
			folder = filepath.Dir(current)
		} else if len(a.files) > 0 {
			folder = filepath.Dir(a.files[0])
		}

		candidate := append([]string(nil), a.files...)
		if folder == "" || !sortImagePathsLikeOpenExplorer(candidate, folder) {
			messageBox(
				a.hwnd,
				"같은 폴더를 열어 둔 Windows 탐색기 창을 찾지 못했습니다.\n\n탐색기에서 해당 폴더를 열어 둔 상태로 다시 선택해주세요.",
				"NightView - 탐색기와 동일하게",
				MB_OK|MB_ICONINFO,
			)
			return
		}
		a.files = candidate
		if idx := findPathIndex(a.files, current); idx >= 0 {
			a.currentIndex = idx
		}
	} else {
		if idx := sortImagePathsKeepingCurrent(a.files, sortMode, current); idx >= 0 {
			a.currentIndex = idx
		}
	}

	a.settings.SortMode = sortMode
	_ = saveSettingsFile(a.settingsPath, a.settings)
	a.invalidate()
}
'''
main = replace_once(main, apply_old, apply_new, "applySortMode exact Explorer order")

# Both openFolder and openImagePath/load-from-shell build their list via
# imageFilesInFolderSorted. Reorder immediately afterwards when the persisted
# mode is Explorer.
scan_anchor = '''	files, err := imageFilesInFolderSorted(folder, a.settings.SortMode)
	if err != nil {
'''
scan_repl = '''	files, err := imageFilesInFolderSorted(folder, a.settings.SortMode)
	if err == nil && a.settings.SortMode == SortExplorer {
		_ = sortImagePathsLikeOpenExplorer(files, folder)
	}
	if err != nil {
'''
main = replace_once(main, scan_anchor, scan_repl, "openFolder Explorer order")

open_anchor = '''	files, e := imageFilesInFolderSorted(folder, a.settings.SortMode)
	if e == nil && len(files) > 0 {
'''
open_repl = '''	files, e := imageFilesInFolderSorted(folder, a.settings.SortMode)
	if e == nil && a.settings.SortMode == SortExplorer {
		_ = sortImagePathsLikeOpenExplorer(files, folder)
	}
	if e == nil && len(files) > 0 {
'''
main = replace_once(main, open_anchor, open_repl, "openImagePath Explorer order")

write("main_windows.go", main)

# Unit tests for exact order filtering / preserving only images.
test = r'''//go:build windows

package main

import (
	"path/filepath"
	"reflect"
	"testing"
)

func TestReorderFilesByExplorerViewUsesExactRelativeOrder(t *testing.T) {
	root := filepath.Clean(`C:\\Pictures`)
	files := []string{
		filepath.Join(root, "A 10.jpg"),
		filepath.Join(root, "A 2.jpg"),
		filepath.Join(root, "A 1.jpg"),
	}
	explorerOrder := []string{
		filepath.Join(root, "not-an-image.txt"),
		filepath.Join(root, "A 2.jpg"),
		filepath.Join(root, "A 10.jpg"),
		filepath.Join(root, "A 1.jpg"),
	}
	matched := reorderFilesByExplorerView(files, explorerOrder)
	if matched != 3 {
		t.Fatalf("matched=%d, want 3", matched)
	}
	want := []string{
		filepath.Join(root, "A 2.jpg"),
		filepath.Join(root, "A 10.jpg"),
		filepath.Join(root, "A 1.jpg"),
	}
	if !reflect.DeepEqual(files, want) {
		t.Fatalf("files=%#v want=%#v", files, want)
	}
}

func TestReorderFilesByExplorerViewIsCaseInsensitiveAndAppendsMissing(t *testing.T) {
	root := filepath.Clean(`C:\\Pictures`)
	files := []string{
		filepath.Join(root, "One.PNG"),
		filepath.Join(root, "Two.JPG"),
		filepath.Join(root, "Transient.webp"),
	}
	explorerOrder := []string{
		filepath.Join(root, "two.jpg"),
		filepath.Join(root, "ONE.png"),
	}
	matched := reorderFilesByExplorerView(files, explorerOrder)
	if matched != 2 {
		t.Fatalf("matched=%d, want 2", matched)
	}
	want := []string{
		filepath.Join(root, "Two.JPG"),
		filepath.Join(root, "One.PNG"),
		filepath.Join(root, "Transient.webp"),
	}
	if !reflect.DeepEqual(files, want) {
		t.Fatalf("files=%#v want=%#v", files, want)
	}
}
'''
write("explorer_view_order_windows_test.go", test)

print("NightView 1.6.10 exact Explorer view-order patch applied.")
