package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	manifestURL = "https://raw.githubusercontent.com/ghltmd4972/NightView-Updates/anime-picker-updates/latest.json"
	appDirName  = "AnimeCharacterRandomPickerUpdater"
	coreName    = "AnimePickerCore.exe"
	logName     = "update.log"
	mutexName   = "Global\\AnimeCharacterRandomPickerGitHubLauncher"
)

type manifest struct {
	Schema      int       `json:"schema"`
	Enabled     bool      `json:"enabled"`
	Version     string    `json:"version"`
	PublishedAt string    `json:"published_at"`
	Core        coreEntry `json:"core"`
}

type coreEntry struct {
	URL    string `json:"url"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

func main() {
	release, already := acquireMutex()
	if release != nil {
		defer release()
	}
	if already {
		return
	}

	appDir, err := localAppDir()
	if err != nil {
		showError("업데이트 폴더를 준비하지 못했습니다.")
		return
	}
	if err := os.MkdirAll(appDir, 0o755); err != nil {
		showError("업데이트 폴더를 만들지 못했습니다.")
		return
	}

	corePath := filepath.Join(appDir, coreName)
	logPath := filepath.Join(appDir, logName)

	if err := updateIfNeeded(corePath, logPath); err != nil {
		appendLog(logPath, "update skipped: "+err.Error())
	}

	if _, err := os.Stat(corePath); err != nil {
		showError("프로그램 파일을 준비하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 실행해주세요.")
		return
	}

	if err := launchCore(corePath, os.Args[1:]); err != nil {
		appendLog(logPath, "launch failed: "+err.Error())
		showError("프로그램을 실행하지 못했습니다.")
		return
	}
}

func updateIfNeeded(corePath, logPath string) error {
	client := &http.Client{Timeout: 6 * time.Second}
	m, err := fetchManifest(client, manifestURL)
	if err != nil {
		return fmt.Errorf("manifest: %w", err)
	}
	if !m.Enabled {
		return nil
	}
	if err := validateManifest(m); err != nil {
		return err
	}

	currentOK, err := fileMatches(corePath, m.Core.Size, m.Core.SHA256)
	if err == nil && currentOK {
		return nil
	}

	tempPath := corePath + ".download"
	_ = os.Remove(tempPath)
	if err := downloadFile(client, m.Core.URL, tempPath); err != nil {
		_ = os.Remove(tempPath)
		return fmt.Errorf("download: %w", err)
	}
	ok, err := fileMatches(tempPath, m.Core.Size, m.Core.SHA256)
	if err != nil || !ok {
		_ = os.Remove(tempPath)
		if err != nil {
			return fmt.Errorf("verify: %w", err)
		}
		return errors.New("verify: sha256 or size mismatch")
	}

	backupPath := corePath + ".bak"
	_ = os.Remove(backupPath)
	if _, err := os.Stat(corePath); err == nil {
		if err := os.Rename(corePath, backupPath); err != nil {
			_ = os.Remove(tempPath)
			return fmt.Errorf("replace old core: %w", err)
		}
	}
	if err := os.Rename(tempPath, corePath); err != nil {
		if _, statErr := os.Stat(backupPath); statErr == nil {
			_ = os.Rename(backupPath, corePath)
		}
		return fmt.Errorf("activate new core: %w", err)
	}
	_ = os.Remove(backupPath)
	appendLog(logPath, "updated to version "+m.Version)
	return nil
}

func fetchManifest(client *http.Client, url string) (manifest, error) {
	var m manifest
	resp, err := client.Get(url)
	if err != nil {
		return m, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return m, fmt.Errorf("http %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return m, err
	}
	body = bytes.TrimPrefix(body, []byte{0xEF, 0xBB, 0xBF})
	if err := json.Unmarshal(body, &m); err != nil {
		return m, err
	}
	return m, nil
}

func validateManifest(m manifest) error {
	if m.Schema != 1 {
		return errors.New("unsupported manifest schema")
	}
	if strings.TrimSpace(m.Core.URL) == "" {
		return errors.New("manifest missing core url")
	}
	if len(strings.TrimSpace(m.Core.SHA256)) != 64 {
		return errors.New("manifest invalid sha256")
	}
	if m.Core.Size <= 0 {
		return errors.New("manifest invalid size")
	}
	return nil
}

func downloadFile(client *http.Client, url, path string) error {
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("http %d", resp.StatusCode)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(f, resp.Body)
	closeErr := f.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func fileMatches(path string, expectedSize int64, expectedSHA string) (bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return false, err
	}
	if st.Size() != expectedSize {
		return false, nil
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return false, err
	}
	got := hex.EncodeToString(h.Sum(nil))
	return strings.EqualFold(got, strings.TrimSpace(expectedSHA)), nil
}

func launchCore(corePath string, args []string) error {
	cmd := exec.Command(corePath, args...)
	cmd.Dir = filepath.Dir(corePath)
	return cmd.Start()
}

func localAppDir() (string, error) {
	base := os.Getenv("LOCALAPPDATA")
	if strings.TrimSpace(base) == "" {
		var err error
		base, err = os.UserCacheDir()
		if err != nil {
			return "", err
		}
	}
	return filepath.Join(base, appDirName), nil
}

func appendLog(path, message string) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = fmt.Fprintf(f, "%s %s\r\n", time.Now().Format(time.RFC3339), message)
}
