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
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	manifestURL = "https://raw.githubusercontent.com/ghltmd4972/NightView-Updates/anime-picker-updates/latest.json"
	appDirName  = "AnimeCharacterRandomPickerUpdater"
	coreName    = "AnimePickerCore.exe"
	logName     = "update.log"
	currentName = "current.json"
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

type currentRecord struct {
	Version      string `json:"version"`
	SHA256       string `json:"sha256"`
	RelativePath string `json:"relative_path"`
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

	logPath := filepath.Join(appDir, logName)
	corePath, err := resolveCore(appDir, logPath)
	if err != nil {
		appendLog(logPath, "resolve core failed: "+err.Error())
		showError("프로그램 파일을 준비하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 실행해주세요.")
		return
	}

	if err := launchCore(corePath, os.Args[1:]); err != nil {
		appendLog(logPath, "launch failed: "+err.Error())
		showError("프로그램을 실행하지 못했습니다.")
		return
	}
}

func resolveCore(appDir, logPath string) (string, error) {
	current, currentPath, hasCurrent := loadCurrentRecord(appDir)
	client := &http.Client{Timeout: 8 * time.Second}
	m, err := fetchManifest(client, manifestURL+"?t="+fmt.Sprint(time.Now().UnixNano()))
	if err == nil && m.Enabled {
		if err := validateManifest(m); err == nil {
			if hasCurrent && !recordMatchesManifest(current, m) {
				if !confirmUpdate(current.Version, m.Version) {
					appendLog(logPath, "update declined; using version "+current.Version)
					return currentPath, nil
				}
			}

			corePath, err := ensureVersionedCore(client, appDir, m)
			if err == nil {
				if err := saveCurrent(appDir, m, corePath); err != nil {
					appendLog(logPath, "save current warning: "+err.Error())
				}
				if err := pruneCachedVersions(appDir, corePath); err != nil {
					appendLog(logPath, "old version cleanup warning: "+err.Error())
				}
				appendLog(logPath, "ready version "+m.Version+" -> "+corePath)
				return corePath, nil
			}
			appendLog(logPath, "update warning: "+err.Error())
		} else {
			appendLog(logPath, "manifest validation warning: "+err.Error())
		}
	} else if err != nil {
		appendLog(logPath, "manifest warning: "+err.Error())
	}

	if hasCurrent {
		appendLog(logPath, "using cached core "+currentPath)
		return currentPath, nil
	}

	legacy := filepath.Join(appDir, coreName)
	if _, err := os.Stat(legacy); err == nil {
		appendLog(logPath, "using legacy core "+legacy)
		return legacy, nil
	}

	if newest := newestCachedCore(appDir); newest != "" {
		appendLog(logPath, "using newest cached core "+newest)
		return newest, nil
	}

	return "", errors.New("no usable core")
}

func ensureVersionedCore(client *http.Client, appDir string, m manifest) (string, error) {
	key := cacheKey(m)
	dir := filepath.Join(appDir, "versions", key)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	corePath := filepath.Join(dir, coreName)

	if ok, err := fileMatches(corePath, m.Core.Size, m.Core.SHA256); err == nil && ok {
		return corePath, nil
	}

	tempPath := filepath.Join(dir, fmt.Sprintf(".download-%d.tmp", os.Getpid()))
	_ = os.Remove(tempPath)
	if err := downloadFile(client, m.Core.URL, tempPath); err != nil {
		_ = os.Remove(tempPath)
		return "", fmt.Errorf("download: %w", err)
	}

	ok, err := fileMatches(tempPath, m.Core.Size, m.Core.SHA256)
	if err != nil || !ok {
		_ = os.Remove(tempPath)
		if err != nil {
			return "", fmt.Errorf("verify: %w", err)
		}
		return "", errors.New("verify: sha256 or size mismatch")
	}

	if _, err := os.Stat(corePath); err == nil {
		_ = os.Remove(corePath)
	}
	if err := os.Rename(tempPath, corePath); err != nil {
		_ = os.Remove(tempPath)
		return "", fmt.Errorf("activate core: %w", err)
	}
	return corePath, nil
}

func cacheKey(m manifest) string {
	version := sanitizeVersion(m.Version)
	hash := strings.ToLower(strings.TrimSpace(m.Core.SHA256))
	if len(hash) > 12 {
		hash = hash[:12]
	}
	if hash == "" {
		hash = "nohash"
	}
	return version + "-" + hash
}

var unsafeVersionChars = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func sanitizeVersion(v string) string {
	v = strings.TrimSpace(v)
	v = unsafeVersionChars.ReplaceAllString(v, "_")
	v = strings.Trim(v, "._-")
	if v == "" {
		return "unknown"
	}
	if len(v) > 80 {
		v = v[:80]
	}
	return v
}

func saveCurrent(appDir string, m manifest, corePath string) error {
	rel, err := filepath.Rel(appDir, corePath)
	if err != nil {
		return err
	}
	rec := currentRecord{
		Version:      m.Version,
		SHA256:       strings.ToLower(strings.TrimSpace(m.Core.SHA256)),
		RelativePath: rel,
	}
	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	path := filepath.Join(appDir, currentName)
	temp := path + ".tmp"
	if err := os.WriteFile(temp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(temp, path)
}

func loadCurrentRecord(appDir string) (currentRecord, string, bool) {
	var rec currentRecord
	data, err := os.ReadFile(filepath.Join(appDir, currentName))
	if err != nil {
		return rec, "", false
	}
	if json.Unmarshal(bytes.TrimPrefix(data, []byte{0xEF, 0xBB, 0xBF}), &rec) != nil {
		return currentRecord{}, "", false
	}
	if strings.TrimSpace(rec.RelativePath) == "" {
		return currentRecord{}, "", false
	}
	path := filepath.Clean(filepath.Join(appDir, rec.RelativePath))
	rel, err := filepath.Rel(appDir, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return currentRecord{}, "", false
	}
	if _, err := os.Stat(path); err != nil {
		return currentRecord{}, "", false
	}
	return rec, path, true
}

func loadCurrent(appDir string) string {
	_, path, ok := loadCurrentRecord(appDir)
	if !ok {
		return ""
	}
	return path
}

func recordMatchesManifest(rec currentRecord, m manifest) bool {
	return strings.TrimSpace(rec.Version) == strings.TrimSpace(m.Version) &&
		strings.EqualFold(strings.TrimSpace(rec.SHA256), strings.TrimSpace(m.Core.SHA256))
}

func pruneCachedVersions(appDir, keepCore string) error {
	versionsDir := filepath.Join(appDir, "versions")
	entries, err := os.ReadDir(versionsDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	keepDir := filepath.Clean(filepath.Dir(keepCore))
	var failures []string
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		dir := filepath.Clean(filepath.Join(versionsDir, entry.Name()))
		if strings.EqualFold(dir, keepDir) {
			continue
		}
		if err := os.RemoveAll(dir); err != nil {
			failures = append(failures, entry.Name()+": "+err.Error())
		}
	}
	legacy := filepath.Join(appDir, coreName)
	if !strings.EqualFold(filepath.Clean(legacy), filepath.Clean(keepCore)) {
		if err := os.Remove(legacy); err != nil && !os.IsNotExist(err) {
			failures = append(failures, coreName+": "+err.Error())
		}
	}
	if len(failures) > 0 {
		return errors.New(strings.Join(failures, "; "))
	}
	return nil
}

func newestCachedCore(appDir string) string {
	pattern := filepath.Join(appDir, "versions", "*", coreName)
	matches, _ := filepath.Glob(pattern)
	type candidate struct {
		path string
		mod  time.Time
	}
	var list []candidate
	for _, p := range matches {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			list = append(list, candidate{path: p, mod: st.ModTime()})
		}
	}
	sort.Slice(list, func(i, j int) bool { return list[i].mod.After(list[j].mod) })
	if len(list) == 0 {
		return ""
	}
	return list[0].path
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
	if strings.TrimSpace(m.Version) == "" {
		return errors.New("manifest missing version")
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
