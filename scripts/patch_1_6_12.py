from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_12.py <source-root>")

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

main = read("main_windows.go")

# Delete key and shell-delete constants.
main = replace_once(
    main,
    "\tVK_RIGHT                            = 0x27\n\tVK_F11                              = 0x7A\n",
    "\tVK_RIGHT                            = 0x27\n\tVK_DELETE                           = 0x2E\n\tVK_F11                              = 0x7A\n",
    "VK_DELETE constant",
)
main = replace_once(
    main,
    "\tBIF_NEWDIALOGSTYLE                  = 0x00000040\n\tMB_OK                               = 0\n",
    "\tBIF_NEWDIALOGSTYLE                  = 0x00000040\n\tFO_DELETE                            = 3\n\tFOF_SILENT                           = 0x0004\n\tFOF_NOCONFIRMATION                   = 0x0010\n\tFOF_ALLOWUNDO                        = 0x0040\n\tFOF_NOERRORUI                        = 0x0400\n\tMB_OK                               = 0\n",
    "recycle bin constants",
)

# SHFILEOPSTRUCTW.
struct_anchor = '''type OPENFILENAME struct {
'''
shell_struct = r'''type SHFILEOPSTRUCT struct {
	Hwnd                  uintptr
	WFunc                 uint32
	PFrom                 *uint16
	PTo                   *uint16
	FFlags                uint16
	FAnyOperationsAborted int32
	HNameMappings         uintptr
	LpszProgressTitle     *uint16
}

'''
main = replace_once(main, struct_anchor, shell_struct + struct_anchor, "SHFILEOPSTRUCT insertion")

# Native shell procedure.
proc_anchor = '''	pDragQueryFile                     = shell32.NewProc("DragQueryFileW")
'''
if proc_anchor not in main:
    # tolerate alignment differences
    m = re.search(r'(?m)^(\s*pDragQueryFile\s*=\s*shell32\.NewProc\("DragQueryFileW"\)\s*)$', main)
    if not m:
        raise SystemExit("DragQueryFileW proc anchor not found")
    line = m.group(1)
    main = main[:m.end()] + '\n\tpSHFileOperation                  = shell32.NewProc("SHFileOperationW")' + main[m.end():]
else:
    main = replace_once(
        main,
        proc_anchor,
        proc_anchor + '\tpSHFileOperation                  = shell32.NewProc("SHFileOperationW")\n',
        "SHFileOperation proc",
    )

# Delete key handling.
main = replace_once(
    main,
    '''	case VK_SPACE:
		a.navigate(1)
	case VK_F11:
''',
    '''	case VK_SPACE:
		a.navigate(1)
	case VK_DELETE:
		a.deleteCurrentImage()
	case VK_F11:
''',
    "Delete key handler",
)

# Pure list-selection helper + recycle bin implementation + app action.
delete_impl = r'''func removeCurrentPathAfterDelete(files []string, currentIndex int) ([]string, int, string, bool) {
	if currentIndex < 0 || currentIndex >= len(files) {
		return files, currentIndex, "", false
	}

	out := make([]string, 0, len(files)-1)
	out = append(out, files[:currentIndex]...)
	out = append(out, files[currentIndex+1:]...)
	if len(out) == 0 {
		return out, -1, "", true
	}

	nextIndex := currentIndex
	if nextIndex >= len(out) {
		nextIndex = len(out) - 1
	}
	return out, nextIndex, out[nextIndex], true
}

func moveFileToRecycleBin(path string) error {
	path = filepath.Clean(path)
	if path == "" || path == "." {
		return fmt.Errorf("삭제할 파일 경로가 없습니다")
	}

	from, err := syscall.UTF16FromString(path)
	if err != nil {
		return err
	}
	// SHFileOperation requires a double-NUL terminated multistring.
	from = append(from, 0)

	op := SHFILEOPSTRUCT{
		Hwnd:   app.hwnd,
		WFunc:  FO_DELETE,
		PFrom:  &from[0],
		FFlags: FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
	}
	ret, _, _ := pSHFileOperation.Call(uintptr(unsafe.Pointer(&op)))
	if ret != 0 {
		return fmt.Errorf("Windows 휴지통 이동 실패 (코드 %d)", int32(ret))
	}
	if op.FAnyOperationsAborted != 0 {
		return fmt.Errorf("삭제 작업이 취소되었습니다")
	}
	return nil
}

func (a *viewerApp) deleteCurrentImage() {
	if a.loading || a.currentPath == "" || a.currentIndex < 0 || a.currentIndex >= len(a.files) {
		return
	}

	path := a.currentPath
	if !strings.EqualFold(filepath.Clean(a.files[a.currentIndex]), filepath.Clean(path)) {
		idx := findPathIndex(a.files, path)
		if idx < 0 {
			return
		}
		a.currentIndex = idx
	}

	if a.aiComparisonActive() {
		a.endAIComparison()
	}

	// GDI+ can keep the source file open while the image is displayed.
	// Release it before asking Windows to move the file to the Recycle Bin.
	a.generation++
	a.loading = false
	a.disposeCurrentImage()

	if err := moveFileToRecycleBin(path); err != nil {
		a.loadPath(path)
		messageBox(a.hwnd, "이미지를 삭제할 수 없습니다.\n\n"+err.Error(), "NightView", MB_OK|MB_ICONERROR)
		return
	}

	files, nextIndex, nextPath, ok := removeCurrentPathAfterDelete(a.files, a.currentIndex)
	if !ok {
		return
	}
	a.files = files
	a.currentIndex = nextIndex

	if nextIndex < 0 {
		a.currentPath = ""
		a.loading = false
		a.setTitle("NightView")
		a.invalidate()
		return
	}

	a.loadPath(nextPath)
}

'''
main = replace_once(
    main,
    "func (a *viewerApp) navigate(delta int) {\n",
    delete_impl + "func (a *viewerApp) navigate(delta int) {\n",
    "delete implementation insertion",
)

write("main_windows.go", main)

tests = r'''//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRemoveCurrentPathAfterDeleteSelectsNext(t *testing.T) {
	files := []string{"a.png", "b.png", "c.png"}
	got, idx, next, ok := removeCurrentPathAfterDelete(files, 1)
	if !ok {
		t.Fatal("delete selection failed")
	}
	if idx != 1 || next != "c.png" {
		t.Fatalf("idx=%d next=%q, want idx=1 next=c.png", idx, next)
	}
	if len(got) != 2 || got[0] != "a.png" || got[1] != "c.png" {
		t.Fatalf("files=%#v", got)
	}
}

func TestRemoveCurrentPathAfterDeleteFallsBackToPreviousAtEnd(t *testing.T) {
	files := []string{"a.png", "b.png", "c.png"}
	got, idx, next, ok := removeCurrentPathAfterDelete(files, 2)
	if !ok {
		t.Fatal("delete selection failed")
	}
	if idx != 1 || next != "b.png" {
		t.Fatalf("idx=%d next=%q, want idx=1 next=b.png", idx, next)
	}
	if len(got) != 2 {
		t.Fatalf("files=%#v", got)
	}
}

func TestRemoveOnlyImageLeavesEmptyViewer(t *testing.T) {
	got, idx, next, ok := removeCurrentPathAfterDelete([]string{"only.png"}, 0)
	if !ok {
		t.Fatal("delete selection failed")
	}
	if len(got) != 0 || idx != -1 || next != "" {
		t.Fatalf("files=%#v idx=%d next=%q", got, idx, next)
	}
}

func TestMoveFileToRecycleBinRemovesSourcePath(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nightview-delete-test.tmp")
	if err := os.WriteFile(path, []byte("delete me"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := moveFileToRecycleBin(path); err != nil {
		t.Skipf("Recycle Bin is unavailable in this Windows runner: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("source still exists after recycle operation: %v", err)
	}
}
'''
write("delete_current_windows_test.go", tests)

print("NightView 1.6.12 Delete-key recycle patch applied.")
