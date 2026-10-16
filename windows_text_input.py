"""Application-local Windows IME setup; never changes installed languages/settings."""
from __future__ import annotations

import ctypes
import os
import uuid


class WindowsTextInput:
    def __init__(self):
        self.available = os.name == "nt"
        self._manager = ctypes.c_void_p()
        self._com_initialized = False
        self._activated = False
        self._owned_contexts = {}
        if not self.available:
            return
        from ctypes import wintypes

        self.imm = ctypes.WinDLL("imm32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.ole = ctypes.WinDLL("ole32", use_last_error=True)
        self.imm.ImmGetContext.argtypes = [wintypes.HWND]
        self.imm.ImmGetContext.restype = wintypes.HANDLE
        self.imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
        self.imm.ImmReleaseContext.restype = wintypes.BOOL
        self.imm.ImmAssociateContextEx.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.DWORD]
        self.imm.ImmAssociateContextEx.restype = wintypes.BOOL
        self.imm.ImmAssociateContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
        self.imm.ImmAssociateContext.restype = wintypes.HANDLE
        self.imm.ImmCreateContext.argtypes = []
        self.imm.ImmCreateContext.restype = wintypes.HANDLE
        self.imm.ImmDestroyContext.argtypes = [wintypes.HANDLE]
        self.imm.ImmDestroyContext.restype = wintypes.BOOL
        self.imm.ImmSetOpenStatus.argtypes = [wintypes.HANDLE, wintypes.BOOL]
        self.imm.ImmSetOpenStatus.restype = wintypes.BOOL
        self.imm.ImmGetConversionStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        self.imm.ImmGetConversionStatus.restype = wintypes.BOOL
        self.imm.ImmSetConversionStatus.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        self.imm.ImmSetConversionStatus.restype = wintypes.BOOL
        self.user.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(wintypes.HKL)]
        self.user.GetKeyboardLayoutList.restype = ctypes.c_int
        self.user.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        self.user.GetKeyboardLayout.restype = wintypes.HKL
        self.user.ActivateKeyboardLayout.argtypes = [wintypes.HKL, wintypes.UINT]
        self.user.ActivateKeyboardLayout.restype = wintypes.HKL
        self.ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.ole.CoInitializeEx.restype = ctypes.c_long
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.ole.CoCreateInstance.restype = ctypes.c_long
        # The modern Windows text service needs a COM apartment on the UI thread.
        self._com_initialized = self.ole.CoInitializeEx(None, 2) >= 0
        clsid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("529a9e6b-6587-4f23-ab9e-9c7d683e3c50").bytes_le)
        iid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("aa80e801-2021-11d2-93e0-0060b067b86e").bytes_le)
        if self.ole.CoCreateInstance(clsid, None, 1, iid, ctypes.byref(self._manager)) >= 0:
            client = wintypes.DWORD()
            self._activated = self._method(3, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))(self._manager, ctypes.byref(client)) >= 0

    def _method(self, index, result, *args):
        vtable = ctypes.cast(self._manager, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(vtable[index])

    def ensure_context(self, hwnd: int) -> bool:
        if not self.available:
            return False
        context = self.imm.ImmGetContext(hwnd)
        if context:
            self.imm.ImmReleaseContext(hwnd, context)
            return True
        # Restore the thread's default input context only if absent. Replacing a
        # live context on every keystroke/focus change would cancel composition.
        self.imm.ImmAssociateContextEx(hwnd, None, 0x10)  # IACE_DEFAULT
        context = self.imm.ImmGetContext(hwnd)
        if context:
            self.imm.ImmReleaseContext(hwnd, context)
            return True
        # Frozen/hosted GUI processes can have no default IMM context at all.
        # Own an explicit one for the field instead of leaving IME disabled.
        if hwnd in self._owned_contexts:
            context, _previous = self._owned_contexts[hwnd]
            self.imm.ImmAssociateContext(hwnd, context)
        else:
            context = self.imm.ImmCreateContext()
            if not context:
                return False
            previous = self.imm.ImmAssociateContext(hwnd, context)
            self._owned_contexts[hwnd] = (context, previous)
        attached = self.imm.ImmGetContext(hwnd)
        if attached:
            self.imm.ImmReleaseContext(hwnd, attached)
        return bool(attached)

    def enable_chinese(self, hwnd: int) -> tuple[bool, str]:
        if not self.available:
            return False, "请通过系统输入法切换中文输入"
        from ctypes import wintypes

        count = self.user.GetKeyboardLayoutList(0, None)
        layouts = (wintypes.HKL * count)()
        self.user.GetKeyboardLayoutList(count, layouts)
        chinese = [layout for layout in layouts if (int(layout) & 0x3FF) == 0x04]
        if not chinese:
            return False, "系统尚未提供中文输入法，请先添加中文输入法"
        current = self.user.GetKeyboardLayout(0)
        layout = current if current in chinese else chinese[0]
        # Flags=0 selects a layout for this UI thread, without changing system
        # preferences or switching every thread in the process.
        if not self.user.ActivateKeyboardLayout(layout, 0):
            return False, "未能切换中文输入法，请用系统语言栏切换后重试"
        if not self.ensure_context(hwnd):
            return False, "当前进程无法连接系统输入法；请关闭程序，在文件管理器中双击启动"
        context = self.imm.ImmGetContext(hwnd)
        if not context:
            return False, "当前进程无法连接系统输入法；请关闭程序，在文件管理器中双击启动"
        try:
            conversion, sentence = wintypes.DWORD(), wintypes.DWORD()
            self.imm.ImmSetOpenStatus(context, True)
            if self.imm.ImmGetConversionStatus(context, ctypes.byref(conversion), ctypes.byref(sentence)):
                self.imm.ImmSetConversionStatus(context, conversion.value | 1, sentence.value)
        finally:
            self.imm.ImmReleaseContext(hwnd, context)
        return True, "已连接中文输入法；如仍显示英文，可按 Shift 切换中英文"

    def close(self):
        for hwnd, (context, previous) in self._owned_contexts.items():
            self.imm.ImmAssociateContext(hwnd, previous)
            self.imm.ImmDestroyContext(context)
        self._owned_contexts.clear()
        if self._manager:
            if self._activated:
                self._method(4, ctypes.c_long)(self._manager)
            self._method(2, ctypes.c_ulong)(self._manager)
            self._manager = ctypes.c_void_p()
        if self._com_initialized:
            self.ole.CoUninitialize()
            self._com_initialized = False
