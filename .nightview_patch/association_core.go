package main

import (
	"fmt"
	"strings"
)

var supportedImageExtensions = []string{
	".jpg", ".jpeg", ".jpe", ".jfif",
	".png", ".gif",
	".bmp", ".dib",
	".tif", ".tiff",
	".ico",
}

func associationOpenCommand(target string) (string, error) {
	target = strings.TrimSpace(target)
	if target == "" {
		return "", fmt.Errorf("empty application path")
	}
	if strings.ContainsRune(target, '"') {
		return "", fmt.Errorf("application path contains an invalid quote")
	}
	return "\"" + target + "\" \"%1\"", nil
}

func uniqueAssociationAppNames(current string) []string {
	candidates := []string{
		current,
		"NightViewSetup.exe",
		"NightViewSetup_1.6.0_Final.exe",
		"NightViewSetup_1.6.0.exe",
		"NightViewSetup_1.5.0.exe",
		"NightViewSetup_1.4.0.exe",
	}
	seen := make(map[string]bool)
	out := make([]string, 0, len(candidates))
	for _, name := range candidates {
		name = strings.TrimSpace(name)
		if name == "" || strings.ContainsAny(name, "\\/\"") {
			continue
		}
		key := strings.ToLower(name)
		if key == "nightview.exe" || seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, name)
	}
	return out
}
