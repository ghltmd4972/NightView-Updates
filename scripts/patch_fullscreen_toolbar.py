import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_fullscreen_toolbar.py <main_windows.go>")

path = Path(sys.argv[1])
src = path.read_text(encoding="utf-8")

def sub_once(pattern: str, repl, label: str, flags=0):
    global src
    new, count = re.subn(pattern, repl, src, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    src = new

# 1) viewer state
struct_pattern = r"(?m)^(?P<i>[ \t]*)hoveredButton[ \t]+int\r?\n(?P=i)fullscreen[ \t]+bool\r?\n(?P=i)savedStyle[ \t]+uintptr"
def struct_repl(m):
    i = m.group("i")
    return (
        f"{i}hoveredButton int\n"
        f"{i}fullscreen bool\n"
        f"{i}fullscreenToolbarVisible bool\n"
        f"{i}savedStyle uintptr"
    )
sub_once(struct_pattern, struct_repl, "viewerApp fields")

# 2) keep fullscreen viewport full-size, add independent visual toolbar height + reveal logic
toolbar_helpers = r'''func (a *viewerApp) toolbarVisualH() int32 {
	return a.dip(46)
}

func (a *viewerApp) fullscreenToolbarRevealH() int32 {
	return a.dip(4)
}

func (a *viewerApp) toolbarH() int32 {
	if a.fullscreen {
		return 0
	}
	return a.toolbarVisualH()
}

func (a *viewerApp) updateFullscreenToolbarVisibility(p POINT) bool {
	if !a.fullscreen {
		if a.fullscreenToolbarVisible {
			a.fullscreenToolbarVisible = false
			a.hoveredButton = 0
			return true
		}
		return false
	}

	if !a.fullscreenToolbarVisible {
		if p.Y >= 0 && p.Y < a.fullscreenToolbarRevealH() {
			a.fullscreenToolbarVisible = true
			return true
		}
		return false
	}

	if p.Y < 0 || p.Y >= a.toolbarVisualH() {
		a.fullscreenToolbarVisible = false
		a.hoveredButton = 0
		return true
	}
	return false
}
'''
sub_once(
    r"(?ms)^func \(a \*viewerApp\) toolbarH\(\) int32 \{.*?^\}\r?\n(?=func )",
    toolbar_helpers,
    "toolbarH",
)

# 3) expose existing button layout while overlay is visible
sub_once(
    r"(?m)^(func \(a \*viewerApp\) buttonLayout\(\) \[\]buttonRect \{\r?\n)"
    r"\tif a\.fullscreen \{\r?\n\t\treturn nil\r?\n\t\}\r?\n\th := a\.toolbarH\(\)",
    r"\g<1>\tif a.fullscreen && !a.fullscreenToolbarVisible {\n"
    r"\t\treturn nil\n\t}\n\th := a.toolbarVisualH()",
    "buttonLayout prefix",
)

# 4) draw fullscreen toolbar as overlay only; status bar stays hidden
sub_once(
    r"(?m)^\tif !a\.fullscreen \{\r?\n"
    r"\t\ta\.drawToolbar\(dc\)\r?\n"
    r"\t\ta\.drawStatus\(dc\)\r?\n"
    r"\t\}",
    "\tif !a.fullscreen {\n"
    "\t\ta.drawToolbar(dc)\n"
    "\t\ta.drawStatus(dc)\n"
    "\t} else if a.fullscreenToolbarVisible {\n"
    "\t\ta.drawToolbar(dc)\n"
    "\t}",
    "paint toolbar block",
)

sub_once(
    r"(?ms)(^func \(a \*viewerApp\) drawToolbar\(dc uintptr\) \{\r?\n\tcr := a\.clientRect\(\)\r?\n)\tth := a\.toolbarH\(\)",
    r"\g<1>\tth := a.toolbarVisualH()",
    "drawToolbar visual height",
)

# 5) let fullscreen overlay buttons receive clicks, but do not start image panning in blank toolbar area
left_down = r'''func (a *viewerApp) onLeftDown(p POINT) {
	if !a.fullscreen || a.fullscreenToolbarVisible {
		for _, b := range a.buttonLayout() {
			if pointInRect(p, b.rect) {
				a.activateButton(b.id)
				return
			}
		}
		if a.fullscreen && a.fullscreenToolbarVisible && p.Y >= 0 && p.Y < a.toolbarVisualH() {
			return
		}
	}
	if a.image == nil || !a.pointInViewport(p) {
		return
	}
	if a.onAICompareLeftDown(p) {
		return
	}
	a.panning = true
	a.panStart = p
	a.panOriginX, a.panOriginY = a.offsetX, a.offsetY
	pSetCapture.Call(a.hwnd)
	c, _, _ := pLoadCursor.Call(0, IDC_SIZEALL)
	pSetCursor.Call(c)
}
'''
sub_once(
    r"(?ms)^func \(a \*viewerApp\) onLeftDown\(p POINT\) \{.*?^\}\r?\n(?=func )",
    left_down,
    "onLeftDown",
)

# 6) reveal/hide overlay from mouse movement before image/AI comparison handling
mouse_move = r'''func (a *viewerApp) onMouseMove(p POINT) {
	toolbarChanged := a.updateFullscreenToolbarVisibility(p)
	if toolbarChanged {
		a.invalidate()
	}

	toolbarActive := a.fullscreen && a.fullscreenToolbarVisible && !a.panning && p.Y >= 0 && p.Y < a.toolbarVisualH()
	if !toolbarActive {
		if a.onAICompareMouseMove(p) {
			return
		}
		if a.panning {
			a.offsetX = a.panOriginX + float64(p.X-a.panStart.X)
			a.offsetY = a.panOriginY + float64(p.Y-a.panStart.Y)
			a.fitMode = FitManual
			a.invalidate()
			return
		}
	}

	old := a.hoveredButton
	a.hoveredButton = 0
	if !a.fullscreen || a.fullscreenToolbarVisible {
		for _, b := range a.buttonLayout() {
			if pointInRect(p, b.rect) {
				a.hoveredButton = b.id
				break
			}
		}
	}
	if old != a.hoveredButton {
		a.invalidate()
	}
	cid := uintptr(IDC_ARROW)
	if a.hoveredButton != 0 {
		cid = IDC_HAND
	}
	c, _, _ := pLoadCursor.Call(0, cid)
	pSetCursor.Call(c)
}
'''
sub_once(
    r"(?ms)^func \(a \*viewerApp\) onMouseMove\(p POINT\) \{.*?^\}\r?\n(?=func )",
    mouse_move,
    "onMouseMove",
)

# 7) double-clicking the visible toolbar must not exit fullscreen
sub_once(
    r"(?m)^\tcase WM_LBUTTONDBLCLK:\r?\n"
    r"\t\tif p := pointFromLParam\(lParam\); app\.pointInViewport\(p\) \{\r?\n"
    r"\t\t\tapp\.toggleFullscreen\(\)\r?\n"
    r"\t\t\}\r?\n"
    r"\t\treturn 0",
    "\tcase WM_LBUTTONDBLCLK:\n"
    "\t\tp := pointFromLParam(lParam)\n"
    "\t\tinFullscreenToolbar := app.fullscreen && app.fullscreenToolbarVisible && p.Y >= 0 && p.Y < app.toolbarVisualH()\n"
    "\t\tif !inFullscreenToolbar && app.pointInViewport(p) {\n"
    "\t\t\tapp.toggleFullscreen()\n"
    "\t\t}\n"
    "\t\treturn 0",
    "fullscreen double-click",
)

# 8) reset overlay state whenever fullscreen toggles
sub_once(
    r"(?ms)(^func \(a \*viewerApp\) toggleFullscreen\(\) \{.*?^\t\}\r?\n)(\ta\.hoveredButton = 0\r?\n\ta\.onViewportChanged\(\)\r?\n\ta\.invalidate\(\)\r?\n^\})",
    r"\g<1>\ta.fullscreenToolbarVisible = false\n\g<2>",
    "toggleFullscreen reset",
)

path.write_text(src, encoding="utf-8", newline="\n")

test_path = path.with_name("fullscreen_toolbar_windows_test.go")
test_path.write_text(r'''//go:build windows

package main

import "testing"

func TestFullscreenToolbarAppearsOnlyAtTopEdgeAndHidesBelowBar(t *testing.T) {
	a := viewerApp{dpi: 96, fullscreen: true}

	if changed := a.updateFullscreenToolbarVisibility(POINT{X: 100, Y: 10}); changed {
		t.Fatal("toolbar appeared away from the top-edge reveal zone")
	}
	if a.fullscreenToolbarVisible {
		t.Fatal("toolbar should still be hidden")
	}

	if changed := a.updateFullscreenToolbarVisibility(POINT{X: 100, Y: 0}); !changed {
		t.Fatal("top edge did not reveal fullscreen toolbar")
	}
	if !a.fullscreenToolbarVisible {
		t.Fatal("fullscreen toolbar should be visible after touching top edge")
	}

	if changed := a.updateFullscreenToolbarVisibility(POINT{X: 100, Y: 20}); changed {
		t.Fatal("toolbar should stay visible while pointer is inside toolbar")
	}
	if !a.fullscreenToolbarVisible {
		t.Fatal("toolbar unexpectedly hid while pointer stayed inside toolbar")
	}

	if changed := a.updateFullscreenToolbarVisibility(POINT{X: 100, Y: a.toolbarVisualH()}); !changed {
		t.Fatal("leaving toolbar did not hide it")
	}
	if a.fullscreenToolbarVisible {
		t.Fatal("toolbar should be hidden after pointer leaves toolbar")
	}
}

func TestFullscreenToolbarIsOverlayAndButtonsRemainInteractive(t *testing.T) {
	a := viewerApp{dpi: 96, fullscreen: true, fullscreenToolbarVisible: true}

	if got := a.toolbarH(); got != 0 {
		t.Fatalf("fullscreen toolbar must not shrink viewport, toolbarH=%d", got)
	}
	if got := a.toolbarVisualH(); got != 46 {
		t.Fatalf("unexpected toolbar visual height: %d", got)
	}
	buttons := a.buttonLayout()
	if len(buttons) == 0 {
		t.Fatal("visible fullscreen toolbar has no interactive buttons")
	}
	for _, b := range buttons {
		if b.rect.Top < 0 || b.rect.Bottom > a.toolbarVisualH() {
			t.Fatalf("button outside fullscreen toolbar: %+v", b.rect)
		}
	}

	a.fullscreenToolbarVisible = false
	if buttons := a.buttonLayout(); buttons != nil {
		t.Fatalf("hidden fullscreen toolbar should not expose buttons: %d", len(buttons))
	}
}

func TestFullscreenToolbarVisibilityResetsOutsideFullscreen(t *testing.T) {
	a := viewerApp{dpi: 96, fullscreen: false, fullscreenToolbarVisible: true, hoveredButton: btnOpen}
	if changed := a.updateFullscreenToolbarVisibility(POINT{X: 0, Y: 0}); !changed {
		t.Fatal("leaving fullscreen should clear toolbar overlay state")
	}
	if a.fullscreenToolbarVisible || a.hoveredButton != 0 {
		t.Fatal("fullscreen toolbar state was not cleared")
	}
}
''', encoding="utf-8", newline="\n")

required = [
    "fullscreenToolbarVisible",
    "fullscreenToolbarRevealH",
    "updateFullscreenToolbarVisibility",
    "else if a.fullscreenToolbarVisible",
    "inFullscreenToolbar :=",
    "th := a.toolbarVisualH()",
]
final_src = path.read_text(encoding="utf-8")
missing = [x for x in required if x not in final_src]
if missing:
    raise SystemExit("missing patched behavior: " + ", ".join(missing))

print("NightView fullscreen top-edge toolbar patch applied successfully.")
