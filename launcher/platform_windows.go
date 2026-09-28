//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

var (
	kernel32         = syscall.NewLazyDLL("kernel32.dll")
	user32           = syscall.NewLazyDLL("user32.dll")
	procCreateMutexW = kernel32.NewProc("CreateMutexW")
	procGetLastError = kernel32.NewProc("GetLastError")
	procMessageBoxW  = user32.NewProc("MessageBoxW")
)

func acquireMutex() (func(), bool) {
	name, _ := syscall.UTF16PtrFromString(mutexName)
	h, _, _ := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if h == 0 {
		return nil, false
	}
	last, _, _ := procGetLastError.Call()
	const errorAlreadyExists = 183
	release := func() { _ = syscall.CloseHandle(syscall.Handle(h)) }
	return release, last == errorAlreadyExists
}

func showError(text string) {
	titlePtr, _ := syscall.UTF16PtrFromString("애니 캐릭터 랜덤 추첨기")
	textPtr, _ := syscall.UTF16PtrFromString(text)
	const mbOK = 0x00000000
	const mbIconError = 0x00000010
	procMessageBoxW.Call(0, uintptr(unsafe.Pointer(textPtr)), uintptr(unsafe.Pointer(titlePtr)), mbOK|mbIconError)
}

func confirmUpdate(oldVersion, newVersion string) bool {
	titlePtr, _ := syscall.UTF16PtrFromString("애니 캐릭터 랜덤 추첨기")
	textPtr, _ := syscall.UTF16PtrFromString(
		"새 업데이트가 있습니다.\n\n현재 버전: " + oldVersion +
			"\n새 버전: " + newVersion +
			"\n\n지금 업데이트하시겠습니까?")
	const mbYesNo = 0x00000004
	const mbIconInformation = 0x00000040
	const idYes = 6
	result, _, _ := procMessageBoxW.Call(
		0,
		uintptr(unsafe.Pointer(textPtr)),
		uintptr(unsafe.Pointer(titlePtr)),
		mbYesNo|mbIconInformation,
	)
	return result == idYes
}
