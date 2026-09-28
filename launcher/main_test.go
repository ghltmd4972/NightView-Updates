package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFetchManifestBOM(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(append([]byte{0xEF, 0xBB, 0xBF}, []byte(`{"schema":1,"enabled":true,"version":"60","core":{"url":"https://example.invalid/core.exe","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size":123}}`)...))
	}))
	defer srv.Close()
	m, err := fetchManifest(srv.Client(), srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	if m.Version != "60" || !m.Enabled || m.Core.Size != 123 {
		t.Fatalf("unexpected manifest: %+v", m)
	}
}

func TestFileMatches(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "core.exe")
	data := []byte("test-core")
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(data)
	ok, err := fileMatches(path, int64(len(data)), hex.EncodeToString(sum[:]))
	if err != nil || !ok {
		t.Fatalf("expected match ok=%v err=%v", ok, err)
	}
}

func TestValidateManifest(t *testing.T) {
	m := manifest{Schema: 1, Enabled: true, Core: coreEntry{URL: "https://example.invalid/core.exe", SHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Size: 1}}
	if err := validateManifest(m); err != nil {
		t.Fatal(err)
	}
}

func TestRecordMatchesManifest(t *testing.T) {
	rec := currentRecord{Version: "62", SHA256: strings.Repeat("a", 64)}
	m := manifest{Version: "62", Core: coreEntry{SHA256: strings.Repeat("A", 64)}}
	if !recordMatchesManifest(rec, m) {
		t.Fatal("expected current record to match manifest")
	}
	m.Version = "63"
	if recordMatchesManifest(rec, m) {
		t.Fatal("different version must require update")
	}
}

func TestPruneCachedVersions(t *testing.T) {
	appDir := t.TempDir()
	keepDir := filepath.Join(appDir, "versions", "63-new")
	oldDir := filepath.Join(appDir, "versions", "62-old")
	if err := os.MkdirAll(keepDir, 0o755); err != nil { t.Fatal(err) }
	if err := os.MkdirAll(oldDir, 0o755); err != nil { t.Fatal(err) }
	keepCore := filepath.Join(keepDir, coreName)
	if err := os.WriteFile(keepCore, []byte("new"), 0o644); err != nil { t.Fatal(err) }
	if err := os.WriteFile(filepath.Join(oldDir, coreName), []byte("old"), 0o644); err != nil { t.Fatal(err) }

	if err := pruneCachedVersions(appDir, keepCore); err != nil { t.Fatal(err) }
	if _, err := os.Stat(keepDir); err != nil { t.Fatalf("keep dir removed: %v", err) }
	if _, err := os.Stat(oldDir); !os.IsNotExist(err) { t.Fatalf("old dir still exists: %v", err) }
}
