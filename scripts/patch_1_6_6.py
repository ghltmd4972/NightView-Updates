import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_1_6_6.py <source-dir>")

root = Path(sys.argv[1])
main = root / "main_windows.go"
compare = root / "comparison_windows.go"
ai = root / "ai_windows.go"

for p in (main, compare, ai):
    if not p.exists():
        raise SystemExit(f"missing source file: {p}")

def replace_once(text, pattern, repl, label, flags=0):
    out, n = re.subn(pattern, repl, text, flags=flags)
    if n != 1:
        raise SystemExit(f"{label}: expected 1 match, found {n}")
    return out

# ---------------------------------------------------------------------------
# main_windows.go: fullscreen top-right window controls
# ---------------------------------------------------------------------------
src = main.read_text(encoding="utf-8")

src = replace_once(
    src,
    r"(?m)^(\s*SW_SHOW\s*=\s*5\s*)$",
    r"\1\n\tSW_MINIMIZE                        = 6",
    "SW_MINIMIZE constant",
)

src = replace_once(
    src,
    r"(?m)^(\s*btnFullscreen\s*=\s*9\s*)$",
    r"\1\n\tbtnMinimize                         = 10\n\tbtnRestore                          = 11\n\tbtnClose                            = 12",
    "window button ids",
)

button_layout_pattern = r'''(?ms)^func \(a \*viewerApp\) buttonLayout\(\) \[\]buttonRect \{
.*?
^\}
'''
button_layout_repl = r'''func (a *viewerApp) buttonLayout() []buttonRect {
	if a.fullscreen && !a.fullscreenToolbarVisible {
		return nil
	}
	h := a.toolbarVisualH()
	x, pad, gap := a.dip(6), a.dip(6), a.dip(4)
	_ = pad
	specs := []struct {
		id    int
		label string
		w     int32
	}{{btnOpen, "열기", 58}, {btnFolder, "폴더", 58}, {btnPrev, "◀", 40}, {btnNext, "▶", 40}, {btnFit, "맞춤", 58}, {btnWidth, "폭", 44}, {btnHeight, "높이", 50}, {btnActual, "100%", 58}, {btnFullscreen, "전체화면", 78}}
	out := make([]buttonRect, 0, len(specs)+3)
	for _, s := range specs {
		w := a.dip(s.w)
		out = append(out, buttonRect{s.id, s.label, RECT{x, a.dip(7), x + w, h - a.dip(7)}})
		x += w + gap
	}
	if a.fullscreen {
		cr := a.clientRect()
		out = append(out, a.fullscreenWindowButtonLayout(cr.Right)...)
	}
	return out
}

func (a *viewerApp) fullscreenWindowButtonLayout(right int32) []buttonRect {
	if right <= 0 {
		return nil
	}
	w := a.dip(46)
	h := a.toolbarVisualH()
	return []buttonRect{
		{btnMinimize, "─", RECT{right - 3*w, 0, right - 2*w, h}},
		{btnRestore, "□", RECT{right - 2*w, 0, right - w, h}},
		{btnClose, "×", RECT{right - w, 0, right, h}},
	}
}

func isFullscreenWindowControlButton(id int) bool {
	return id == btnMinimize || id == btnRestore || id == btnClose
}
'''
src = replace_once(src, button_layout_pattern, button_layout_repl, "buttonLayout", flags=re.M | re.S)

draw_toolbar_pattern = r'''(?ms)^func \(a \*viewerApp\) drawToolbar\(dc uintptr\) \{
.*?
^\}
'''
draw_toolbar_repl = r'''func (a *viewerApp) drawToolbar(dc uintptr) {
	cr := a.clientRect()
	th := a.toolbarVisualH()
	fillRect(dc, RECT{0, 0, cr.Right, th}, rgb(21, 21, 21))
	drawLine(dc, 0, th-1, cr.Right, th-1, rgb(42, 42, 42))
	for _, b := range a.buttonLayout() {
		bg, border := rgb(38, 38, 38), rgb(58, 58, 58)
		windowControl := isFullscreenWindowControlButton(b.id)
		if windowControl {
			bg, border = rgb(21, 21, 21), rgb(21, 21, 21)
		}
		if a.hoveredButton == b.id {
			if b.id == btnClose {
				bg, border = rgb(196, 43, 28), rgb(196, 43, 28)
			} else {
				bg, border = rgb(52, 52, 52), rgb(78, 78, 78)
			}
		}
		fillRect(dc, b.rect, bg)
		if !windowControl {
			frameRect(dc, b.rect, border)
		}
		drawText(dc, b.label, b.rect, a.fontNormal, rgb(242, 242, 242), DT_CENTER|DT_VCENTER|DT_SINGLELINE)
	}
}
'''
src = replace_once(src, draw_toolbar_pattern, draw_toolbar_repl, "drawToolbar", flags=re.M | re.S)

activate_pattern = r'''(?ms)^func \(a \*viewerApp\) activateButton\(id int\) \{
.*?
^\}
'''
activate_repl = r'''func (a *viewerApp) activateButton(id int) {
	switch id {
	case btnOpen:
		a.chooseFile()
	case btnFolder:
		a.chooseFolder()
	case btnPrev:
		a.navigate(-1)
	case btnNext:
		a.navigate(1)
	case btnFit:
		a.applyFit(FitWindow)
	case btnWidth:
		a.applyFit(FitWidth)
	case btnHeight:
		a.applyFit(FitHeight)
	case btnActual:
		a.applyFit(FitActual)
	case btnFullscreen:
		a.toggleFullscreen()
	case btnMinimize:
		pShowWindow.Call(a.hwnd, SW_MINIMIZE)
	case btnRestore:
		if a.fullscreen {
			a.toggleFullscreen()
		}
	case btnClose:
		pPostMessage.Call(a.hwnd, WM_CLOSE, 0, 0)
	}
}
'''
src = replace_once(src, activate_pattern, activate_repl, "activateButton", flags=re.M | re.S)

# Clean comparison snapshot on both close and destroy paths.
src = replace_once(
    src,
    r"(?ms)(\tcase WM_CLOSE:\r?\n.*?\t\tcancelAIUpscale\(\)\r?\n)\t\tapp\.endAIComparison\(\)",
    r"\1\t\tapp.clearAICompareCandidate()",
    "WM_CLOSE comparison cleanup",
)
src = replace_once(
    src,
    r"(?ms)(\tcase WM_DESTROY:\r?\n.*?\t\tcancelAIUpscale\(\)\r?\n)(\t\tpKillTimer\.Call)",
    r"\1\t\tapp.clearAICompareCandidate()\n\2",
    "WM_DESTROY comparison cleanup",
)

main.write_text(src, encoding="utf-8", newline="\n")

# ---------------------------------------------------------------------------
# comparison_windows.go: owned original snapshot + cleanup
# ---------------------------------------------------------------------------
src = compare.read_text(encoding="utf-8")

src = replace_once(
    src,
    r'''(?ms)^type aiCompareCandidate struct \{
\toriginalPath string
\tresultPath   string
\toriginalSHA  string
\tscale        int
\}
''',
    r'''type aiCompareCandidate struct {
	originalPath string
	resultPath   string
	originalSHA  string
	scale        int
	cleanupPath  string
}
''',
    "aiCompareCandidate fields",
)

set_candidate_pattern = r'''(?ms)^func \(a \*viewerApp\) setAICompareCandidate\(original, result string, scale int, originalSHA string\) \{
.*?
^\}
'''
set_candidate_repl = r'''func (a *viewerApp) clearAICompareCandidate() {
	if aiCompare.active {
		a.endAIComparison()
	}
	cleanupPath := aiCompare.candidate.cleanupPath
	aiCompare.candidate = aiCompareCandidate{}
	if cleanupPath != "" {
		_ = os.RemoveAll(cleanupPath)
	}
}

func (a *viewerApp) setAICompareCandidate(original, result string, scale int, originalSHA string) {
	a.setAICompareCandidateWithCleanup(original, result, scale, originalSHA, "")
}

func (a *viewerApp) setAICompareCandidateWithCleanup(original, result string, scale int, originalSHA, cleanupPath string) {
	if scale != 2 && scale != 4 {
		if cleanupPath != "" {
			_ = os.RemoveAll(cleanupPath)
		}
		return
	}
	a.clearAICompareCandidate()
	aiCompare.candidate = aiCompareCandidate{
		originalPath: filepath.Clean(original),
		resultPath:   filepath.Clean(result),
		originalSHA:  strings.ToLower(strings.TrimSpace(originalSHA)),
		scale:        scale,
		cleanupPath:  cleanupPath,
	}
}

func stageAICompareOriginalSnapshot(original string) (string, string, error) {
	root, err := os.MkdirTemp("", "NightView-AI-Compare-*")
	if err != nil {
		return "", "", err
	}
	dst := filepath.Join(root, filepath.Base(original))
	if err := copyFileExclusive(original, dst); err != nil {
		_ = os.RemoveAll(root)
		return "", "", err
	}
	return dst, root, nil
}
'''
src = replace_once(src, set_candidate_pattern, set_candidate_repl, "setAICompareCandidate", flags=re.M | re.S)

compare.write_text(src, encoding="utf-8", newline="\n")

# ---------------------------------------------------------------------------
# ai_windows.go: preserve original snapshot before destructive 4x overwrite
# ---------------------------------------------------------------------------
src = ai.read_text(encoding="utf-8")

overwrite_repl = r'''\tcase IDYES:
\t\tsnapshotPath, snapshotCleanup, snapshotErr := stageAICompareOriginalSnapshot(input)
\t\tif snapshotErr != nil {
\t\t\ta.onAIUpscaleErrorText("원본 비교용 임시 복사본을 만들지 못해 덮어쓰기를 중단했습니다.\\n\\n" + snapshotErr.Error())
\t\t\treturn
\t\t}
\t\twasCurrent := strings.EqualFold(filepath.Clean(a.currentPath), filepath.Clean(input))
\t\tif wasCurrent {
\t\t\ta.disposeCurrentImage()
\t\t}
\t\tif err := overwriteAI4KOriginal(result, input); err != nil {
\t\t\t_ = os.RemoveAll(snapshotCleanup)
\t\t\tif wasCurrent {
\t\t\t\ta.openImagePath(input)
\t\t\t}
\t\t\ta.onAIUpscaleErrorText("원본 파일에 덮어쓰지 못했습니다.\\n\\n" + err.Error())
\t\t\treturn
\t\t}
\t\tsavedPath = input
\t\ta.setAICompareCandidateWithCleanup(snapshotPath, savedPath, scale, inputSHA, snapshotCleanup)
'''
overwrite_start = src.find("\tcase IDYES:")
overwrite_end = src.find("\tcase aiIDNo:", overwrite_start)
if overwrite_start < 0 or overwrite_end < 0:
    raise SystemExit(f"AI 4K overwrite branch boundaries not found: start={overwrite_start}, end={overwrite_end}")
if src.count("\tcase IDYES:") != 1:
    raise SystemExit(f"AI 4K overwrite branch is ambiguous: found {src.count(chr(9) + 'case IDYES:')} IDYES branches")
src = src[:overwrite_start] + overwrite_repl + src[overwrite_end:]

src = replace_once(
    src,
    r'''messageBox\(a\.hwnd, "AI 4K 결과를 원본 파일에 덮어썼습니다\.\\n\\n"\+savedPath, "NightView AI 4K", MB_OK\|MB_ICONINFO\)''',
    r'''messageBox(a.hwnd, "AI 4K 결과를 원본 파일에 덮어썼습니다.\n\n"+savedPath+"\n\nC 키로 덮어쓰기 전 원본과 AI 4K 결과를 비교할 수 있습니다.", "NightView AI 4K", MB_OK|MB_ICONINFO)''',
    "overwrite completion message",
)

ai.write_text(src, encoding="utf-8", newline="\n")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
(root / "window_controls_windows_test.go").write_text(r'''//go:build windows

package main

import "testing"

func TestFullscreenWindowButtonsAreRightAligned(t *testing.T) {
	a := viewerApp{dpi: 96, fullscreen: true, fullscreenToolbarVisible: true}
	buttons := a.fullscreenWindowButtonLayout(1920)
	if len(buttons) != 3 {
		t.Fatalf("expected 3 fullscreen window buttons, got %d", len(buttons))
	}
	wantIDs := []int{btnMinimize, btnRestore, btnClose}
	for i, want := range wantIDs {
		if buttons[i].id != want {
			t.Fatalf("button %d id=%d want=%d", i, buttons[i].id, want)
		}
		if buttons[i].rect.Top != 0 || buttons[i].rect.Bottom != a.toolbarVisualH() {
			t.Fatalf("button %d vertical rect=%+v", i, buttons[i].rect)
		}
	}
	if buttons[2].rect.Right != 1920 {
		t.Fatalf("close button must touch right edge, got %d", buttons[2].rect.Right)
	}
	if buttons[0].rect.Left != 1920-3*a.dip(46) {
		t.Fatalf("unexpected minimize button left edge: %d", buttons[0].rect.Left)
	}
}

func TestFullscreenWindowControlClassification(t *testing.T) {
	for _, id := range []int{btnMinimize, btnRestore, btnClose} {
		if !isFullscreenWindowControlButton(id) {
			t.Fatalf("window control %d not classified", id)
		}
	}
	if isFullscreenWindowControlButton(btnOpen) {
		t.Fatal("normal toolbar button classified as window control")
	}
}
''', encoding="utf-8", newline="\n")

(root / "comparison_snapshot_windows_test.go").write_text(r'''//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAICompareSnapshotSurvivesOriginalOverwriteAndCleansUp(t *testing.T) {
	d := t.TempDir()
	original := filepath.Join(d, "원본.png")
	before := []byte("original-image-bytes")
	if err := os.WriteFile(original, before, 0o644); err != nil {
		t.Fatal(err)
	}
	sha, _, err := fileSHA256(original)
	if err != nil {
		t.Fatal(err)
	}

	snapshot, cleanup, err := stageAICompareOriginalSnapshot(original)
	if err != nil {
		t.Fatal(err)
	}
	if cleanup == "" || snapshot == "" {
		t.Fatal("snapshot paths were not created")
	}
	if err := os.WriteFile(original, []byte("4k-overwritten-image"), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := os.ReadFile(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(before) {
		t.Fatalf("snapshot changed after original overwrite: %q", got)
	}
	snapshotSHA, _, err := fileSHA256(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if snapshotSHA != sha {
		t.Fatalf("snapshot SHA=%s want=%s", snapshotSHA, sha)
	}

	a := viewerApp{}
	a.setAICompareCandidateWithCleanup(snapshot, original, 4, sha, cleanup)
	if aiCompare.candidate.originalPath != snapshot {
		t.Fatalf("candidate original=%q want=%q", aiCompare.candidate.originalPath, snapshot)
	}
	if aiCompare.candidate.resultPath != original {
		t.Fatalf("candidate result=%q want=%q", aiCompare.candidate.resultPath, original)
	}
	if aiCompare.candidate.cleanupPath != cleanup {
		t.Fatalf("candidate cleanup=%q want=%q", aiCompare.candidate.cleanupPath, cleanup)
	}

	a.clearAICompareCandidate()
	if _, err := os.Stat(cleanup); !os.IsNotExist(err) {
		t.Fatalf("comparison snapshot directory was not removed: %v", err)
	}
}

func TestReplacingAICompareCandidateCleansPreviousOwnedSnapshot(t *testing.T) {
	d := t.TempDir()
	oldRoot := filepath.Join(d, "old-snapshot")
	if err := os.MkdirAll(oldRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	oldFile := filepath.Join(oldRoot, "original.png")
	if err := os.WriteFile(oldFile, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}

	a := viewerApp{}
	aiCompare = aiCompareState{candidate: aiCompareCandidate{
		originalPath: oldFile,
		resultPath:   filepath.Join(d, "old-result.png"),
		originalSHA:  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		scale:        4,
		cleanupPath:  oldRoot,
	}}
	a.setAICompareCandidate(
		filepath.Join(d, "new-original.png"),
		filepath.Join(d, "new-result.png"),
		2,
		"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	)
	if _, err := os.Stat(oldRoot); !os.IsNotExist(err) {
		t.Fatalf("previous owned snapshot was not removed: %v", err)
	}
	a.clearAICompareCandidate()
}
''', encoding="utf-8", newline="\n")

# Basic post-patch assertions.
checks = {
    main: [
        "btnMinimize", "btnRestore", "btnClose", "SW_MINIMIZE",
        "fullscreenWindowButtonLayout", "pPostMessage.Call(a.hwnd, WM_CLOSE, 0, 0)",
        "app.clearAICompareCandidate()",
    ],
    compare: [
        "cleanupPath", "stageAICompareOriginalSnapshot",
        "setAICompareCandidateWithCleanup", "clearAICompareCandidate",
    ],
    ai: [
        "snapshotPath, snapshotCleanup", "setAICompareCandidateWithCleanup",
        "C 키로 덮어쓰기 전 원본과 AI 4K 결과를 비교할 수 있습니다.",
    ],
}
for p, needles in checks.items():
    text = p.read_text(encoding="utf-8")
    missing = [n for n in needles if n not in text]
    if missing:
        raise SystemExit(f"{p.name}: missing {missing}")

print("NightView 1.6.6 window controls + AI 4K overwrite comparison patch applied.")
