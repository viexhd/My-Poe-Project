"""Windows low-level mouse + keyboard hook (WH_MOUSE_LL / WH_KEYBOARD_LL).

Used by the Alt+drag area selection to see left-button presses, moves
and Esc anywhere on screen, and to *swallow* the few events that belong
to the gesture so the game never sees them. It sends no input.

The hook runs on its own thread with a Win32 message loop. Callbacks
must return quickly: Windows silently drops a hook that keeps blocking
input (LowLevelHooksTimeout). They receive ``MouseEvent`` / ``KeyEvent``
and return True to swallow the event.

Limitations:
* Windows only; ``start()`` is a no-op elsewhere.
* If PoE runs elevated (as administrator) this app must too, or
  Windows (UIPI) hides PoE's input from the hook. Use run-admin.bat.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import sys
import threading
from typing import Callable, Optional

from ..area_select.gesture import KeyEvent, MouseEvent

log = logging.getLogger("poe_qol.input.mouse_hook")

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
LLMHF_INJECTED = 0x01
LLKHF_INJECTED = 0x10
VK_ESCAPE = 0x1B
_VK_MODS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
_MOUSE_KINDS = {WM_MOUSEMOVE: "move", WM_LBUTTONDOWN: "down", WM_LBUTTONUP: "up"}

_IS_WIN = sys.platform.startswith("win")
LRESULT = wt.LPARAM


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


if _IS_WIN:
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
    _user32.SetWindowsHookExW.restype = wt.HHOOK
    _user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    _user32.CallNextHookEx.restype = LRESULT
    _user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    _user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wt.HMODULE


def modifiers_down() -> frozenset[str]:
    """Modifier keys physically held right now (Windows only)."""
    if not _IS_WIN:
        return frozenset()
    return frozenset(name for name, vk in _VK_MODS.items()
                     if _user32.GetAsyncKeyState(vk) & 0x8000)


class LowLevelInputHook:
    def __init__(self, on_mouse: Callable[[MouseEvent], bool],
                 on_key: Callable[[KeyEvent], bool]) -> None:
        self._on_mouse = on_mouse
        self._on_key = on_key
        self._thread: Optional[threading.Thread] = None
        self._tid = 0
        self._ready = threading.Event()
        self._procs: tuple = ()
        self.error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if not _IS_WIN:
            self.error = "low-level hooks need Windows"
            return False
        if self.running:
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="area-select-hook")
        self._thread.start()
        self._ready.wait(2.0)
        return self.running and self.error is None

    def stop(self) -> None:
        if not self.running:
            return
        _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread.join(2.0)  # type: ignore[union-attr]
        self._thread = None

    # ---- hook thread ----
    def _mouse_cb(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            kind = _MOUSE_KINDS.get(w_param)
            if kind is not None:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                try:
                    ev = MouseEvent(kind, info.pt.x, info.pt.y, modifiers_down(),
                                    bool(info.flags & LLMHF_INJECTED))
                    if self._on_mouse(ev):
                        return 1
                except Exception:
                    log.exception("mouse hook callback failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _key_cb(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN,
                                       WM_KEYUP, WM_SYSKEYUP):
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            try:
                key = "esc" if info.vkCode == VK_ESCAPE else f"vk{info.vkCode}"
                ev = KeyEvent(key, w_param in (WM_KEYDOWN, WM_SYSKEYDOWN),
                              bool(info.flags & LLKHF_INJECTED))
                if self._on_key(ev):
                    return 1
            except Exception:
                log.exception("key hook callback failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self) -> None:
        self._tid = _kernel32.GetCurrentThreadId()
        mouse_proc = HOOKPROC(self._mouse_cb)
        key_proc = HOOKPROC(self._key_cb)
        self._procs = (mouse_proc, key_proc)   # keep alive
        hmod = _kernel32.GetModuleHandleW(None)
        h_mouse = _user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, hmod, 0)
        h_key = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, key_proc, hmod, 0)
        if not h_mouse or not h_key:
            self.error = f"SetWindowsHookExW failed ({ctypes.get_last_error()})"
            log.error(self.error)
            for h in (h_mouse, h_key):
                if h:
                    _user32.UnhookWindowsHookEx(h)
            self._ready.set()
            return
        log.info("area-select input hook installed")
        self._ready.set()
        msg = wt.MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnhookWindowsHookEx(h_mouse)
            _user32.UnhookWindowsHookEx(h_key)
            log.info("area-select input hook removed")
