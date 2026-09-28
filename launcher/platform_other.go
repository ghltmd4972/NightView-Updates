//go:build !windows

package main

func acquireMutex() (func(), bool) { return func() {}, false }
func showError(text string) {}
func confirmUpdate(oldVersion, newVersion string) bool { return true }
