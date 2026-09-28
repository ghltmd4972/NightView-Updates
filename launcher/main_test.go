package main

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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
