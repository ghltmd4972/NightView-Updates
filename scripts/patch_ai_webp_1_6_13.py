from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_ai_webp_1_6_13.py <source-root>")

root = Path(sys.argv[1])

def read(name):
    return (root / name).read_text(encoding="utf-8")

def write(name, value):
    (root / name).write_text(value, encoding="utf-8", newline="\n")

def replace_one(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return source.replace(old, new, 1)

core = read("ai_core.go")
core = replace_one(
    core,
    'case ".png", ".jpg", ".jpeg", ".jpe", ".jfif":',
    'case ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp":',
    "WebP AI support",
)
write("ai_core.go", core)

core_tests = read("ai_core_test.go")
core_tests = replace_one(
    core_tests,
    '[]string{"a.png", "a.JPG", "a.jpeg", "a.jfif"}',
    '[]string{"a.png", "a.JPG", "a.jpeg", "a.jfif", "a.webp", "A.WEBP"}',
    "supported AI formats test",
)
core_tests = replace_one(
    core_tests,
    '[]string{"a.gif", "a.bmp", "a.tif", "a.ico", "a.webp"}',
    '[]string{"a.gif", "a.bmp", "a.tif", "a.ico"}',
    "unsupported AI formats test",
)
write("ai_core_test.go", core_tests)

windows = read("ai_windows.go")
windows = replace_one(
    windows,
    '현재 AI 업스케일은 JPG/JPEG/PNG 이미지만 지원합니다.\\n\\nGIF/BMP/TIFF/ICO는 이후 이미지 변환 단계를 추가한 뒤 지원할 수 있습니다.',
    '현재 AI 업스케일은 JPG/JPEG/PNG/WEBP 이미지를 지원합니다.\\n\\nGIF/BMP/TIFF/ICO는 아직 지원하지 않습니다.',
    "input format 안내",
)
windows = replace_one(
    windows,
    'args, err := buildAIEngineArgs(inst, input, tmpOutput, scale)',
    '''engineInput, releaseEngineInput, err := prepareAIEngineInput(input)
	if err != nil {
		a.finishAIUpscale("", sourceSHA, false, fmt.Errorf("AI 입력 이미지 변환 실패: %w", err))
		return
	}
	defer releaseEngineInput()
	args, err := buildAIEngineArgs(inst, engineInput, tmpOutput, scale)''',
    "AI engine input conversion",
)
windows = replace_one(
    windows,
    'choice := messageBoxResult(a.hwnd, prompt, "NightView AI 4K 저장", aiMBYesNoCancel|MB_ICONINFO)',
    '''choice := aiIDNo
	if aiNeedsSafePNGSave(input) {
		messageBox(a.hwnd, "WEBP 원본은 변경하지 않습니다.\\n\\nAI 4K 결과를 PNG로 다른 이름으로 저장하세요.", "NightView AI 4K 저장", MB_OK|MB_ICONINFO)
	} else {
		choice = messageBoxResult(a.hwnd, prompt, "NightView AI 4K 저장", aiMBYesNoCancel|MB_ICONINFO)
	}''',
    "WebP safe 4K saving",
)
write("ai_windows.go", windows)

helper = r'''//go:build windows

package main

import (
    "fmt"
    "os"
    "path/filepath"
    "strings"
)

// Keep the original bytes and hash. Convert only the AI engine's input.
func aiNeedsSafePNGSave(input string) bool {
    return strings.EqualFold(filepath.Ext(input), ".webp") || isWebPContent(input)
}

func prepareAIEngineInput(input string) (string, func(), error) {
    noop := func() {}
    if !aiNeedsSafePNGSave(input) {
        return input, noop, nil
    }
    converted, err := transcodeWebPToTempPNG(input)
    if err != nil {
        return "", noop, fmt.Errorf("WebP to PNG: %w", err)
    }
    return converted, func() { _ = os.Remove(converted) }, nil
}
'''
write("ai_webp_input_windows.go", helper)

tests = r'''//go:build windows

package main

import (
    "os"
    "path/filepath"
    "strings"
    "testing"
)

func TestAIWebPPreparedAsPNGAndOriginalUntouched(t *testing.T) {
    source := filepath.Join("testdata", "tiny.webp")
    before, _, err := fileSHA256(source)
    if err != nil { t.Fatal(err) }
    path, cleanup, err := prepareAIEngineInput(source)
    if err != nil { t.Fatal(err) }
    defer cleanup()
    if !strings.EqualFold(filepath.Ext(path), ".png") || path == source {
        t.Fatalf("incorrect AI input: %q", path)
    }
    cfg, format, err := imageConfig(path)
    if err != nil || format != "png" || cfg.Width <= 0 || cfg.Height <= 0 {
        t.Fatalf("invalid converted PNG: %v %q %+v", err, format, cfg)
    }
    after, _, err := fileSHA256(source)
    if err != nil || before != after { t.Fatal("original WebP was modified") }
    if !aiNeedsSafePNGSave(source) { t.Fatal("WebP overwrite must be blocked") }
    cleanup()
    if _, err := os.Stat(path); !os.IsNotExist(err) { t.Fatalf("temporary PNG was not cleaned: %v", err) }
}

func TestAINativePNGNoConversion(t *testing.T) {
    p := filepath.Join("testdata", "tiny.png")
    out, cleanup, err := prepareAIEngineInput(p)
    if err != nil || out != p { t.Fatalf("PNG should pass unchanged: %q %v", out, err) }
    cleanup()
    if aiNeedsSafePNGSave(p) { t.Fatal("PNG must retain existing 4K save choices") }
}

func TestAIWebPContentDisguisedAsJPG(t *testing.T) {
    src := filepath.Join("testdata", "tiny.webp")
    bytes, err := os.ReadFile(src)
    if err != nil { t.Fatal(err) }
    target := filepath.Join(t.TempDir(), "disguised.jpg")
    if err := os.WriteFile(target, bytes, 0600); err != nil { t.Fatal(err) }
    if !aiNeedsSafePNGSave(target) { t.Fatal("WebP magic must be detected") }
    converted, cleanup, err := prepareAIEngineInput(target)
    if err != nil { t.Fatal(err) }
    defer cleanup()
    _, format, err := imageConfig(converted)
    if err != nil || format != "png" { t.Fatalf("disguised WebP not converted: %v %q", err, format) }
}
'''
write("ai_webp_input_windows_test.go", tests)
print("NightView 1.6.13 WebP AI input patch staged (source only).")
