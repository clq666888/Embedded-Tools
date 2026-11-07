"""Select a file or folder with one Windows Explorer open dialog."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import uuid


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, value: str) -> None:
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


class _Filter(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("pattern", ctypes.c_wchar_p)]


class _Object(ctypes.Structure):
    _fields_ = [("vtable", ctypes.POINTER(ctypes.c_void_p))]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_CLSID_OPEN = _GUID("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
_IID_OPEN = _GUID("D57C7288-D4AD-4768-BE02-9D969532D960")
_IID_DIALOG_EVENTS = _GUID("973510DB-7D7F-452B-8975-74A85828D354")
_IID_UNKNOWN = _GUID("00000000-0000-0000-C000-000000000046")
_IID_SHELL_ITEM = _GUID("43826D1E-E718-42EE-BC55-A1E261C37BFE")
_SIGDN_FILESYSPATH = 0x80058000


def _method(obj: ctypes.c_void_p, index: int, result, *args):
    address = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][index]
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(address)


def _check(hr: int) -> None:
    if hr < 0:
        raise OSError(f"Windows 文件选择窗口出错：0x{hr & 0xFFFFFFFF:08X}")


def _release(obj: ctypes.c_void_p) -> None:
    if obj.value:
        _method(obj, 2, ctypes.c_ulong)(obj)


def _shell_path(item: ctypes.c_void_p, ole32) -> str:
    name = ctypes.c_void_p()
    try:
        _check(_method(item, 5, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
            item, _SIGDN_FILESYSPATH, ctypes.byref(name)))
        return ctypes.wstring_at(name.value)
    finally:
        if name.value:
            ole32.CoTaskMemFree(name)


def _dialog_item_path(dialog: ctypes.c_void_p, index: int, ole32) -> str:
    item = ctypes.c_void_p()
    try:
        hr = _method(dialog, index, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
            dialog, ctypes.byref(item))
        if hr < 0 or not item.value:
            return ""
        return _shell_path(item, ole32)
    except OSError:
        return ""
    finally:
        _release(item)


def _confirm_button_under_cursor() -> bool:
    user32 = ctypes.windll.user32
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    user32.WindowFromPoint.argtypes = [_Point]
    user32.WindowFromPoint.restype = ctypes.c_void_p
    user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
    user32.GetDlgCtrlID.restype = ctypes.c_int
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p
    point = _Point()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return False
    window = user32.WindowFromPoint(point)
    for _ in range(3):
        if not window:
            break
        if user32.GetDlgCtrlID(window) == 1:  # Windows common dialog's Open button.
            return True
        window = user32.GetParent(window)
    return False


class _DialogEvents:
    def __init__(self, dialog: ctypes.c_void_p, ole32) -> None:
        self.dialog = dialog
        self.ole32 = ole32
        self.chosen = ""
        self.error: Exception | None = None
        self.ready = False
        self.refs = 1
        call = ctypes.WINFUNCTYPE
        self.callbacks = [
            call(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(self._query),
            call(ctypes.c_ulong, ctypes.c_void_p)(self._addref),
            call(ctypes.c_ulong, ctypes.c_void_p)(self._release),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(self._no_op),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(self._folder_changing),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(self._folder_changed),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(self._no_op),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                 ctypes.POINTER(ctypes.c_uint))(self._default_response),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(self._no_op),
            call(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                 ctypes.POINTER(ctypes.c_uint))(self._default_response),
        ]
        self.vtable = (ctypes.c_void_p * len(self.callbacks))(
            *(ctypes.cast(callback, ctypes.c_void_p).value for callback in self.callbacks))
        self.obj = _Object(ctypes.cast(self.vtable, ctypes.POINTER(ctypes.c_void_p)))
        self.pointer = ctypes.cast(ctypes.pointer(self.obj), ctypes.c_void_p)

    def _query(self, _self, iid, output) -> int:
        requested = bytes(iid.contents.data)
        if requested in (bytes(_IID_UNKNOWN.data), bytes(_IID_DIALOG_EVENTS.data)):
            output[0] = self.pointer.value
            self.refs += 1
            return 0
        output[0] = None
        return -2147467262  # E_NOINTERFACE

    def _addref(self, _self) -> int:
        self.refs += 1
        return self.refs

    def _release(self, _self) -> int:
        self.refs -= 1
        return self.refs

    def _no_op(self, *_args) -> int:
        return 0

    def _folder_changed(self, *_args) -> int:
        self.ready = True
        return 0

    def _folder_changing(self, _self, _dialog, destination_item) -> int:
        if not self.ready:
            return 0
        try:
            destination = _shell_path(ctypes.c_void_p(destination_item), self.ole32)
            selected = _dialog_item_path(self.dialog, 14, self.ole32)
            if (selected and _confirm_button_under_cursor() and Path(selected).is_dir()
                    and os.path.normcase(os.path.normpath(selected)) ==
                    os.path.normcase(os.path.normpath(destination))):
                self.chosen = selected
                _check(_method(self.dialog, 23, ctypes.c_long, ctypes.c_long)(self.dialog, 0))
                return 1  # S_FALSE: prevent navigation to the chosen folder.
        except Exception as exc:
            self.error = exc
        return 0

    def _default_response(self, _self, _dialog, _item, response) -> int:
        response[0] = 0
        return 0

def choose_source(owner: int, initial_directory: str) -> str:
    """Return the selected file/folder path, or an empty string on cancel."""
    if sys.platform != "win32":
        raise OSError("此选择窗口仅支持 Windows")
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_ulong,
                                       ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    shell32.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                                                      ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

    initialized = ole32.CoInitializeEx(None, 2)  # STA, required for shell dialogs
    _check(initialized)
    dialog = ctypes.c_void_p()
    cookie = ctypes.c_uint()
    advised = False
    try:
        _check(ole32.CoCreateInstance(ctypes.byref(_CLSID_OPEN), None, 1,
                                       ctypes.byref(_IID_OPEN), ctypes.byref(dialog)))
        _check(_method(dialog, 9, ctypes.c_long, ctypes.c_uint)(dialog, 0x40 | 0x800 | 0x1000))
        filters = (_Filter * 2)(
            _Filter("工程及固件文件", "*.zip;*.bin;*.hex;*.ihx;*.elf;*.axf;*.out;*.map"),
            _Filter("所有文件", "*.*"))
        _check(_method(dialog, 4, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(_Filter))(
            dialog, len(filters), filters))
        _check(_method(dialog, 17, ctypes.c_long, ctypes.c_wchar_p)(dialog, "选择工程文件夹、ZIP 或固件文件"))
        _check(_method(dialog, 18, ctypes.c_long, ctypes.c_wchar_p)(dialog, "选择"))
        initial = Path(initial_directory)
        if initial.is_dir():
            folder = ctypes.c_void_p()
            try:
                hr = shell32.SHCreateItemFromParsingName(str(initial), None,
                                                          ctypes.byref(_IID_SHELL_ITEM), ctypes.byref(folder))
                if hr >= 0:
                    _check(_method(dialog, 11, ctypes.c_long, ctypes.c_void_p)(dialog, folder))
            finally:
                _release(folder)
        events = _DialogEvents(dialog, ole32)
        _check(_method(dialog, 7, ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint))(
            dialog, events.pointer, ctypes.byref(cookie)))
        advised = True
        hr = _method(dialog, 3, ctypes.c_long, ctypes.c_void_p)(dialog, owner)
        if events.error:
            raise events.error
        if events.chosen:
            return events.chosen
        if hr == -2147023673:  # HRESULT_FROM_WIN32(ERROR_CANCELLED)
            return ""
        _check(hr)
        return _dialog_item_path(dialog, 20, ole32)
    finally:
        if advised:
            _method(dialog, 8, ctypes.c_long, ctypes.c_uint)(dialog, cookie)
        _release(dialog)
        ole32.CoUninitialize()
