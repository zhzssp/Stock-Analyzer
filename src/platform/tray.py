from __future__ import annotations

import os
import sys
import threading
import webbrowser
from collections.abc import Callable

ID_OPEN = 1001
ID_EXIT = 1002
WM_TRAY = 0x0401
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
IDI_APPLICATION = 32512
WS_OVERLAPPED = 0x00000000
MF_STRING = 0
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100


class Tray:
    def __init__(self, url: str, on_exit: Callable[[], None] | None = None) -> None:
        self.url = url
        self.on_exit = on_exit
        self._thread: threading.Thread | None = None
        self._hwnd = 0
        self._stop = threading.Event()
        self._keep: list[object] = []

    def start(self) -> None:
        if os.name != "nt":
            return
        self._thread = threading.Thread(target=self._loop, name="sa-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if os.name != "nt" or not self._hwnd:
            return
        try:
            import ctypes

            ctypes.windll.user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        except Exception:
            pass

    def _loop(self) -> None:
        try:
            self._run_win32()
        except Exception:
            pass

    def _run_win32(self) -> None:
        import ctypes
        from ctypes import wintypes

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hWnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINT),
            ]

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        user32.LoadIconW.restype = wintypes.HICON
        nid_ref: dict[str, NOTIFYICONDATA] = {}

        def _open() -> None:
            try:
                webbrowser.open(self.url)
            except Exception:
                pass

        def _exit_app() -> None:
            if self.on_exit:
                try:
                    self.on_exit()
                except Exception:
                    pass
            user32.PostQuitMessage(0)

        def _popup(hwnd: int) -> None:
            menu = user32.CreatePopupMenu()
            user32.AppendMenuW(menu, MF_STRING, ID_OPEN, "打开工作台")
            user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "退出助手")
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(hwnd)
            cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, hwnd, None)
            user32.DestroyMenu(menu)
            user32.PostMessageW(hwnd, 0, 0, 0)
            if cmd == ID_OPEN:
                _open()
            elif cmd == ID_EXIT:
                _exit_app()

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam == WM_LBUTTONUP:
                    _open()
                elif lparam == WM_RBUTTONUP:
                    _popup(hwnd)
                return 0
            if msg == WM_DESTROY:
                data = nid_ref.get("nid")
                if data is not None:
                    try:
                        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                    except Exception:
                        pass
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROC(wnd_proc)
        wc = WNDCLASS()
        wc.lpfnWndProc = proc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "StockAnalyzerTray"
        self._keep.extend([proc, wc])
        if not user32.RegisterClassW(ctypes.byref(wc)):
            pass
        hwnd = user32.CreateWindowExW(
            0,
            wc.lpszClassName,
            "Stock-Analyzer",
            WS_OVERLAPPED,
            0,
            0,
            0,
            0,
            0,
            0,
            wc.hInstance,
            None,
        )
        if not hwnd:
            return
        self._hwnd = hwnd
        icon = user32.LoadIconW(None, IDI_APPLICATION)
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = icon
        nid.szTip = "Stock-Analyzer 在托盘运行"
        nid_ref["nid"] = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

        msg = MSG()
        while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def start_tray(url: str, on_exit: Callable[[], None] | None = None) -> Tray | None:
    if os.name != "nt" or "pytest" in sys.modules:
        return None
    tray = Tray(url, on_exit=on_exit)
    tray.start()
    return tray
