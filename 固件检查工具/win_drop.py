"""Explorer file and folder drop support using the Windows shell API."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import sys
import tkinter as tk
from tkinter import messagebox


WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def enable_file_drop(root, callback):
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    hooks = []
    dropped: queue.Queue[list[str]] = queue.Queue()

    def deliver() -> None:
        try:
            while True:
                paths = dropped.get_nowait()
                try:
                    callback(paths)
                except Exception as exc:
                    messagebox.showerror("拖入失败", str(exc), parent=root)
        except queue.Empty:
            pass
        finally:
            try:
                root.after(50, deliver)
            except tk.TclError:
                pass

    def make_proc():
        state = {"old": None}

        def wndproc(window, message, wparam, lparam):
            if message == WM_DROPFILES:
                handle = wparam
                try:
                    count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                    paths = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(handle, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(handle, index, buffer, length + 1)
                        paths.append(buffer.value)
                    dropped.put(paths)
                except Exception:
                    # Never let a Python exception escape a native window callback.
                    pass
                finally:
                    shell32.DragFinish(handle)
                return 0
            return user32.CallWindowProcW(state["old"], window, message, wparam, lparam)

        return proc_type(wndproc), state

    for hwnd in {root.winfo_id(), user32.GetParent(root.winfo_id())}:
        if not hwnd:
            continue
        proc, state = make_proc()
        old_proc = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
        if not old_proc:
            raise OSError("无法启用拖放")
        state["old"] = old_proc
        shell32.DragAcceptFiles(hwnd, True)
        hooks.append((hwnd, proc, state))
    root.after(50, deliver)
    return hooks
