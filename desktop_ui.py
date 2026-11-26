"""Small native Windows launcher; no GUI framework or Tcl runtime is required."""
import ctypes
from ctypes import wintypes as w
import logging
import os
import queue
import threading
import webbrowser

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, WPARAM, LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE),
                ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR)]


class LauncherWindow:
    def __init__(self, directory, servers, save_key, notice, start_servers=True):
        self.directory, self.servers, self.save_key = directory, servers, save_key
        self.events = queue.Queue()
        self.closing = threading.Event()
        self.ready = False
        self.handle = None
        self.worker = None
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self._declare_api()
        self.callback = WNDPROC(self._dispatch)
        self.instance = self.kernel.GetModuleHandleW(None)
        self.class_name = "CombatFitnessLauncher"
        window_class = WNDCLASS()
        window_class.lpfnWndProc = self.callback
        window_class.hInstance = self.instance
        window_class.hCursor = self.user.LoadCursorW(None, ctypes.c_void_p(32512))
        window_class.hbrBackground = self.user.GetSysColorBrush(15)
        window_class.lpszClassName = self.class_name
        if not self.user.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.font = self.gdi.CreateFontW(-17, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "맑은 고딕")
        self.title_font = self.gdi.CreateFontW(-25, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 0, 0, "맑은 고딕")
        self.handle = self.user.CreateWindowExW(0x10000, self.class_name,
            "전투체력 관리 — 실행 중에는 이 창을 유지하세요", 0x00CA0000,
            -2147483648, -2147483648, 655, 385, None, None, self.instance, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.control("STATIC", "장병 전투체력 관리", 22, 18, 600, 38, font=self.title_font)
        self.status = self.control("STATIC", "프로그램을 시작하고 있습니다…", 22, 65, 600, 30)
        self.control("STATIC", "Claude API 키 (최초 1회)", 22, 109, 580, 24)
        self.entry = self.control("EDIT", "", 22, 139, 465, 29, 5, 0x008100A0)
        self.control("BUTTON", "키 저장", 499, 139, 115, 29, 2, 0x10000)
        self.notice = self.control("STATIC", notice, 22, 180, 594, 44)
        self.control("STATIC", "키는 현재 Windows 계정에 암호화하여 저장됩니다.\n계획 생성에는 인터넷과 사용 가능한 Claude API 계정이 필요합니다.",
                     22, 227, 600, 49)
        self.open_button = self.control("BUTTON", "웹 화면 열기", 22, 292, 160, 34, 1, 0x10000)
        self.user.EnableWindow(self.open_button, False)
        self.control("BUTTON", "저장 폴더 열기", 194, 292, 160, 34, 3, 0x10000)
        self.control("BUTTON", "종료", 499, 292, 115, 34, 4, 0x10000)
        if start_servers:
            self.user.SetTimer(self.handle, 1, 100, None)
            self.worker = threading.Thread(target=self._start, daemon=True)
            self.worker.start()

    def _declare_api(self):
        def define(dll, name, result, *args):
            function = getattr(dll, name)
            function.restype, function.argtypes = result, args

        define(self.kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
        define(self.user, "RegisterClassW", w.ATOM, ctypes.POINTER(WNDCLASS))
        define(self.user, "UnregisterClassW", w.BOOL, w.LPCWSTR, w.HINSTANCE)
        define(self.user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
               ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU,
               w.HINSTANCE, ctypes.c_void_p)
        define(self.user, "DefWindowProcW", LRESULT, w.HWND, w.UINT, WPARAM, LPARAM)
        define(self.user, "SendMessageW", LRESULT, w.HWND, w.UINT, WPARAM, LPARAM)
        define(self.user, "SetWindowTextW", w.BOOL, w.HWND, w.LPCWSTR)
        define(self.user, "GetWindowTextLengthW", ctypes.c_int, w.HWND)
        define(self.user, "GetWindowTextW", ctypes.c_int, w.HWND, w.LPWSTR, ctypes.c_int)
        define(self.user, "EnableWindow", w.BOOL, w.HWND, w.BOOL)
        define(self.user, "SetTimer", WPARAM, w.HWND, WPARAM, w.UINT, ctypes.c_void_p)
        define(self.user, "KillTimer", w.BOOL, w.HWND, WPARAM)
        define(self.user, "LoadCursorW", w.HANDLE, w.HINSTANCE, ctypes.c_void_p)
        define(self.user, "GetSysColorBrush", w.HBRUSH, ctypes.c_int)
        define(self.user, "ShowWindow", w.BOOL, w.HWND, ctypes.c_int)
        define(self.user, "DestroyWindow", w.BOOL, w.HWND)
        define(self.user, "GetMessageW", ctypes.c_int, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
        define(self.user, "IsDialogMessageW", w.BOOL, w.HWND, ctypes.POINTER(w.MSG))
        define(self.user, "TranslateMessage", w.BOOL, ctypes.POINTER(w.MSG))
        define(self.user, "DispatchMessageW", LRESULT, ctypes.POINTER(w.MSG))
        define(self.user, "PostQuitMessage", None, ctypes.c_int)
        define(self.user, "MessageBoxW", ctypes.c_int, w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT)
        define(self.gdi, "CreateFontW", w.HFONT, *([ctypes.c_int] * 5), *([w.DWORD] * 8), w.LPCWSTR)
        define(self.gdi, "DeleteObject", w.BOOL, w.HGDIOBJ)

    def control(self, kind, text, x, y, width, height, identifier=0, style=0, font=None):
        handle = self.user.CreateWindowExW(0, kind, text, 0x50000000 | style,
            x, y, width, height, self.handle, identifier, self.instance, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.SendMessageW(handle, 0x30, font or self.font, 1)
        return handle

    def _start(self):
        try:
            address = self.servers.start()
            if self.closing.is_set():
                self.servers.stop()
            else:
                self.events.put((True, address))
        except Exception:
            logging.exception("Server startup failed")
            self.events.put((False, "시작하지 못했습니다. 저장 폴더의 launcher.log를 확인하세요."))

    def _command(self, identifier):
        if identifier == 1 and self.ready:
            webbrowser.open(self.servers.url)
        elif identifier == 2:
            size = self.user.GetWindowTextLengthW(self.entry)
            value = ctypes.create_unicode_buffer(size + 1)
            self.user.GetWindowTextW(self.entry, value, len(value))
            key = value.value.strip()
            if not key or any(ch.isspace() for ch in key):
                self.user.MessageBoxW(self.handle, "공백 없이 API 키를 입력하세요.", "API 키 확인", 0x10)
                return
            notice = self.save_key(key)
            self.user.SetWindowTextW(self.entry, "")
            self.user.SetWindowTextW(self.notice, notice)
        elif identifier == 3:
            os.startfile(self.directory)
        elif identifier == 4:
            self.user.DestroyWindow(self.handle)

    def _dispatch(self, handle, message, wparam, lparam):
        try:
            if message == 0x111:  # WM_COMMAND
                self._command(wparam & 0xFFFF)
                return 0
            if message == 0x113:  # WM_TIMER
                try:
                    success, value = self.events.get_nowait()
                except queue.Empty:
                    return 0
                self.user.KillTimer(handle, 1)
                self.ready = success
                self.user.SetWindowTextW(self.status, "실행 중: " + value if success else value)
                self.user.EnableWindow(self.open_button, success)
                if success:
                    webbrowser.open(value)
                return 0
            if message == 0x10:  # WM_CLOSE
                self.user.DestroyWindow(handle)
                return 0
            if message == 0x02:  # WM_DESTROY
                self.closing.set()
                if self.worker is None or not self.worker.is_alive():
                    self.servers.stop()
                self.user.PostQuitMessage(0)
                return 0
        except Exception:
            logging.exception("Launcher event failed")
        return self.user.DefWindowProcW(handle, message, wparam, lparam)

    def run(self):
        self.user.ShowWindow(self.handle, 5)
        message = w.MSG()
        while True:
            result = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0:
                break
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.user.IsDialogMessageW(self.handle, ctypes.byref(message)):
                self.user.TranslateMessage(ctypes.byref(message))
                self.user.DispatchMessageW(ctypes.byref(message))

    def close(self):
        self.closing.set()
        if self.handle:
            self.user.DestroyWindow(self.handle)
            self.handle = None
        if self.worker is None or not self.worker.is_alive():
            self.servers.stop()
        self.gdi.DeleteObject(self.font)
        self.gdi.DeleteObject(self.title_font)
        self.user.UnregisterClassW(self.class_name, self.instance)
