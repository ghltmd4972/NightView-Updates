//go:build !windows

package main

func acquireMutex() (func(), bool) { return func() {}, false }
func showError(text string)        {}
