from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_9.py <source-root>")

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

core = read("core.go")
core = replace_once(
    core,
    '\tSortExtensionAsc   = "extension_asc"\n\tSortRandom         = "random"\n',
    '\tSortExtensionAsc   = "extension_asc"\n\tSortExplorer       = "explorer"\n\tSortRandom         = "random"\n',
    "sort constant",
)
core = replace_once(
    core,
    '\tSortExtensionAsc:   {},\n\tSortRandom:         {},\n',
    '\tSortExtensionAsc:   {},\n\tSortExplorer:       {},\n\tSortRandom:         {},\n',
    "valid sort modes",
)
core = replace_once(
    core,
    '\tcase SortExtensionAsc:\n\t\tif a.ext != b.ext {\n\t\t\treturn a.ext < b.ext\n\t\t}\n\tcase SortRandom:\n',
    '\tcase SortExtensionAsc:\n\t\tif a.ext != b.ext {\n\t\t\treturn a.ext < b.ext\n\t\t}\n\tcase SortExplorer:\n\t\treturn explorerLogicalLess(a.base, b.base)\n\tcase SortRandom:\n',
    "explorer comparator branch",
)
write("core.go", core)

main = read("main_windows.go")
main = replace_once(
    main,
    '\tcmdSortExtensionAsc                 = 1040\n\tcmdSortRandom                       = 1041\n',
    '\tcmdSortExtensionAsc                 = 1040\n\tcmdSortRandom                       = 1041\n\tcmdSortExplorer                     = 1042\n',
    "sort command constant",
)

menu_anchor = '''		if nameMenu != 0 {
			af, df := uintptr(MF_STRING), uintptr(MF_STRING)
			if a.settings.SortMode == SortNameDesc {
				df |= MF_CHECKED
			} else if a.settings.SortMode == SortNameAsc {
				af |= MF_CHECKED
			}
			appendMenu(nameMenu, af, cmdSortNameAsc, "오름차순")
			appendMenu(nameMenu, df, cmdSortNameDesc, "내림차순")
			label := mustUTF16("파일명 자연 정렬")
			pAppendMenu.Call(sortMenu, MF_POPUP|MF_STRING, nameMenu, uintptr(unsafe.Pointer(label)))
		}

'''
menu_replacement = menu_anchor + '''		explorerFlags := uintptr(MF_STRING)
		if a.settings.SortMode == SortExplorer {
			explorerFlags |= MF_CHECKED
		}
		appendMenu(sortMenu, explorerFlags, cmdSortExplorer, "탐색기와 동일하게")

'''
main = replace_once(main, menu_anchor, menu_replacement, "sort menu explorer entry")

main = replace_once(
    main,
    '\tcase cmdSortRandom:\n\t\ta.applySortMode(SortRandom)\n\tcase cmdAIUpscale2X:\n',
    '\tcase cmdSortRandom:\n\t\ta.applySortMode(SortRandom)\n\tcase cmdSortExplorer:\n\t\ta.applySortMode(SortExplorer)\n\tcase cmdAIUpscale2X:\n',
    "sort command handling",
)
write("main_windows.go", main)

windows_impl = r'''//go:build windows

package main

import (
	"strings"
	"syscall"
	"unsafe"
)

var (
	explorerSortShlwapi        = syscall.NewLazyDLL("shlwapi.dll")
	explorerSortStrCmpLogicalW = explorerSortShlwapi.NewProc("StrCmpLogicalW")
)

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
'''
write("explorer_sort_windows.go", windows_impl)

other_impl = r'''//go:build !windows

package main

func explorerLogicalLess(a, b string) bool {
	return naturalLess(a, b)
}
'''
write("explorer_sort_other.go", other_impl)

windows_test = r'''//go:build windows

package main

import (
	"reflect"
	"testing"
)

func TestExplorerLogicalCompareUsesWindowsNaturalOrder(t *testing.T) {
	if explorerLogicalCompare("2.png", "10.png") >= 0 {
		t.Fatal("Windows Explorer logical comparison did not put 2.png before 10.png")
	}
	if explorerLogicalCompare("10.png", "2.png") <= 0 {
		t.Fatal("Windows Explorer logical comparison did not put 10.png after 2.png")
	}
}

func TestExplorerSortModeMatchesWindowsLogicalNameOrder(t *testing.T) {
	files := []string{"C:/x/10.png", "C:/x/2.png", "C:/x/1.png"}
	sortImagePaths(files, SortExplorer)
	want := []string{"C:/x/1.png", "C:/x/2.png", "C:/x/10.png"}
	if !reflect.DeepEqual(files, want) {
		t.Fatalf("explorer sort = %#v, want %#v", files, want)
	}
}
'''
write("explorer_sort_windows_test.go", windows_test)

core_test = read("core_test.go")
anchor = '''func TestRandomSortPreservesSet(t *testing.T) {
'''
test_insert = '''func TestExplorerSortModeIsValid(t *testing.T) {
	if _, ok := validSortModes[SortExplorer]; !ok {
		t.Fatal("SortExplorer is not a valid persisted sort mode")
	}
	files := []string{"/x/10.png", "/x/2.png", "/x/1.png"}
	sortImagePaths(files, SortExplorer)
	if len(files) != 3 {
		t.Fatalf("explorer sort changed file count: %d", len(files))
	}
}

'''
core_test = replace_once(core_test, anchor, test_insert + anchor, "core explorer sort test")
write("core_test.go", core_test)

print("NightView 1.6.9 Explorer sorting patch applied.")
