//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

// Windows 传统控制台:切 UTF-8 代码页防中文乱码 + 开 VT 让 ANSI 颜色生效。
func setupConsole() {
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	_, _, _ = kernel32.NewProc("SetConsoleOutputCP").Call(65001)
	getStdHandle := kernel32.NewProc("GetStdHandle")
	setConsoleMode := kernel32.NewProc("SetConsoleMode")
	getConsoleMode := kernel32.NewProc("GetConsoleMode")
	h, _, _ := getStdHandle.Call(uintptr(^uint32(10) + 1)) // STD_OUTPUT_HANDLE = -11
	var mode uint32
	_, _, _ = getConsoleMode.Call(h, uintptr(unsafe.Pointer(&mode)))
	_, _, _ = setConsoleMode.Call(h, uintptr(mode|0x0004)) // ENABLE_VIRTUAL_TERMINAL_PROCESSING
}
