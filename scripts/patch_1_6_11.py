from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_11.py <source-root>")

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

# State flag: only image-file startup defers the first visible window.
main = replace_once(
    main,
    "\tfullscreenToolbarVisible          bool\n\tsavedStyle                        uintptr\n",
    "\tfullscreenToolbarVisible          bool\n\tdeferInitialReveal                 bool\n\tsavedStyle                        uintptr\n",
    "viewerApp deferred reveal field",
)

# Pure startup helpers make the intended behavior testable.
helpers = r'''func shouldDeferInitialReveal(path string) bool {
	path = filepath.Clean(strings.TrimSpace(path))
	if path == "" || path == "." {
		return false
	}
	st, err := os.Stat(path)
	if err != nil || st.IsDir() {
		return false
	}
	return isSupportedImagePath(path) || isWebPContent(path)
}

func initialWindowStyle(deferReveal bool) uintptr {
	style := uintptr(WS_OVERLAPPEDWINDOW | WS_VISIBLE)
	if deferReveal {
		style = uintptr(WS_OVERLAPPEDWINDOW)
	}
	return style
}

'''
main = replace_once(
    main,
    "func main() {\n",
    helpers + "func main() {\n",
    "startup helper insertion",
)

# Decide whether this launch must stay invisible until the selected image is ready.
main = replace_once(
    main,
    "\tapp.settingsPath = settingsFilePath()\n\tapp.settings = loadSettingsFile(app.settingsPath)\n",
    "\tapp.settingsPath = settingsFilePath()\n\tapp.settings = loadSettingsFile(app.settingsPath)\n\tapp.deferInitialReveal = shouldDeferInitialReveal(startup.OpenPath)\n",
    "deferred startup decision",
)

# Do not create a visible 1280x800 intermediate window for image launches.
old_create = '''	hwnd, _, e := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(cls)), uintptr(unsafe.Pointer(title)), WS_OVERLAPPEDWINDOW|WS_VISIBLE, uptr32(x), uptr32(y), uintptr(w), uintptr(h), 0, 0, hi, 0)
'''
new_create = '''	windowStyle := initialWindowStyle(app.deferInitialReveal)
	hwnd, _, e := pCreateWindowEx.Call(0, uintptr(unsafe.Pointer(cls)), uintptr(unsafe.Pointer(title)), windowStyle, uptr32(x), uptr32(y), uintptr(w), uintptr(h), 0, 0, hi, 0)
'''
main = replace_once(main, old_create, new_create, "CreateWindow startup style")

# Standalone NightView keeps the current immediate fullscreen startup.
# Image launches remain hidden until WM_IMAGE_READY succeeds.
old_show = '''	app.hwnd = hwnd
	applyDarkTitleBar(hwnd)
	pShowWindow.Call(hwnd, SW_SHOW)
	pUpdateWindow.Call(hwnd)
	app.toggleFullscreen()
'''
new_show = '''	app.hwnd = hwnd
	applyDarkTitleBar(hwnd)
	if !app.deferInitialReveal {
		pShowWindow.Call(hwnd, SW_SHOW)
		pUpdateWindow.Call(hwnd)
		app.toggleFullscreen()
	}
'''
main = replace_once(main, old_show, new_show, "initial ShowWindow block")

# Prepare fullscreen geometry while still hidden. No WS_VISIBLE and no
# SWP_SHOWWINDOW are used here, so the intermediate window can never flash.
deferred_helpers = r'''func (a *viewerApp) prepareDeferredInitialFullscreen() bool {
	if !a.deferInitialReveal || a.hwnd == 0 {
		return false
	}
	a.deferInitialReveal = false
	if a.fullscreen {
		return true
	}

	pGetWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&a.savedRect)))
	style, _, _ := pGetWindowLongPtr.Call(a.hwnd, uptr32(GWL_STYLE))
	a.savedStyle = style

	mon, _, _ := pMonitorFromWindow.Call(a.hwnd, MONITOR_DEFAULTTONEAREST)
	mi := MONITORINFO{CbSize: uint32(unsafe.Sizeof(MONITORINFO{}))}
	pGetMonitorInfo.Call(mon, uintptr(unsafe.Pointer(&mi)))

	pSetWindowLongPtr.Call(a.hwnd, uptr32(GWL_STYLE), WS_POPUP)
	a.fullscreen = true
	pSetWindowPos.Call(
		a.hwnd,
		0,
		uptr32(mi.RcMonitor.Left),
		uptr32(mi.RcMonitor.Top),
		uintptr(mi.RcMonitor.Right-mi.RcMonitor.Left),
		uintptr(mi.RcMonitor.Bottom-mi.RcMonitor.Top),
		SWP_FRAMECHANGED,
	)
	a.fullscreenToolbarVisible = false
	a.hoveredButton = 0
	a.onViewportChanged()
	return true
}

func (a *viewerApp) showPreparedInitialWindow() {
	if a.hwnd == 0 {
		return
	}
	a.invalidate()
	pShowWindow.Call(a.hwnd, SW_SHOW)
	pUpdateWindow.Call(a.hwnd)
}

'''
main = replace_once(
    main,
    "func (a *viewerApp) onImageReady(gen uint64) {\n",
    deferred_helpers + "func (a *viewerApp) onImageReady(gen uint64) {\n",
    "deferred reveal helpers insertion",
)

# Reveal only after a successful asset is installed and fitted to fullscreen.
old_ready = r'''	a.loading = false
	if res.err != nil {
		a.invalidate()
		messageBox(a.hwnd, "이미지를 열 수 없습니다.\n\n"+res.err.Error(), "NightView", MB_OK|MB_ICONERROR)
		return
	}
	a.disposeCurrentImage()
	a.image = res.asset
	a.fitMode = FitWindow
	a.scale = 1
	a.applyFit(FitWindow)
	a.startAnimationTimer()
	a.invalidate()
'''
new_ready = r'''	a.loading = false
	if res.err != nil {
		if a.prepareDeferredInitialFullscreen() {
			a.showPreparedInitialWindow()
		} else {
			a.invalidate()
		}
		messageBox(a.hwnd, "이미지를 열 수 없습니다.\n\n"+res.err.Error(), "NightView", MB_OK|MB_ICONERROR)
		return
	}
	a.disposeCurrentImage()
	a.image = res.asset
	a.fitMode = FitWindow
	a.scale = 1
	deferredReveal := a.prepareDeferredInitialFullscreen()
	a.applyFit(FitWindow)
	a.startAnimationTimer()
	a.invalidate()
	if deferredReveal {
		a.showPreparedInitialWindow()
	}
'''
main = replace_once(main, old_ready, new_ready, "onImageReady reveal order")

write("main_windows.go", main)

tests = r'''//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestInitialImageLaunchUsesHiddenWindowStyle(t *testing.T) {
	style := initialWindowStyle(true)
	if style&WS_VISIBLE != 0 {
		t.Fatalf("deferred image startup window unexpectedly has WS_VISIBLE: %#x", style)
	}
	if style&WS_OVERLAPPEDWINDOW != WS_OVERLAPPEDWINDOW {
		t.Fatalf("deferred image startup lost overlapped base style: %#x", style)
	}
}

func TestStandaloneLaunchKeepsVisibleWindowStyle(t *testing.T) {
	style := initialWindowStyle(false)
	if style&WS_VISIBLE == 0 {
		t.Fatalf("standalone startup window is not visible: %#x", style)
	}
}

func TestShouldDeferInitialRevealOnlyForImageFiles(t *testing.T) {
	dir := t.TempDir()
	png := filepath.Join(dir, "image.png")
	if err := os.WriteFile(png, []byte("not decoded in this test"), 0o600); err != nil {
		t.Fatal(err)
	}
	if !shouldDeferInitialReveal(png) {
		t.Fatal("supported image file should defer the initial window reveal")
	}

	txt := filepath.Join(dir, "note.txt")
	if err := os.WriteFile(txt, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if shouldDeferInitialReveal(txt) {
		t.Fatal("non-image file must not defer the initial window reveal")
	}
	if shouldDeferInitialReveal(dir) {
		t.Fatal("folder launch must not defer the initial window reveal")
	}
	if shouldDeferInitialReveal("") {
		t.Fatal("standalone launch must not defer the initial window reveal")
	}
}
'''
write("startup_reveal_windows_test.go", tests)

print("NightView 1.6.11 deferred first-image reveal patch applied.")
