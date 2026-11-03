"""Win32 window information helpers for DaVinci discovery."""


class Win32WindowInfoAdapter:
    def __init__(
        self,
        *,
        is_available,
        user32=None,
        kernel32=None,
        ctypes_module=None,
        wintypes_module=None,
        rect_cls=None,
        enum_windows_proc_cls=None,
        process_query_limited_information=0,
    ):
        self.is_available = is_available
        self.user32 = user32
        self.kernel32 = kernel32
        self.ctypes = ctypes_module
        self.wintypes = wintypes_module
        self.rect_cls = rect_cls
        self.enum_windows_proc_cls = enum_windows_proc_cls
        self.process_query_limited_information = process_query_limited_information

    def get_window_title(self, hwnd):
        if not self.is_available or not self.user32 or not self.ctypes:
            return ''

        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ''
        buffer = self.ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def get_window_rect(self, hwnd):
        if not self.is_available or not self.user32 or not self.rect_cls or not self.ctypes:
            return None

        rect = self.rect_cls()
        if not self.user32.GetWindowRect(hwnd, self.ctypes.byref(rect)):
            return None
        return (
            float(rect.left),
            float(rect.top),
            float(rect.right - rect.left),
            float(rect.bottom - rect.top),
        )

    def get_window_process_id(self, hwnd):
        if not self.is_available or not hwnd or not self.user32 or not self.wintypes:
            return 0

        pid = self.wintypes.DWORD()
        try:
            self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
            return int(pid.value or 0)
        except Exception:
            return 0

    def get_window_process_path(self, hwnd):
        if (
            not self.is_available
            or not self.user32
            or not self.kernel32
            or not self.wintypes
            or not self.ctypes
        ):
            return ''

        pid = self.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        if not pid.value:
            return ''

        handle = self.kernel32.OpenProcess(
            self.process_query_limited_information,
            False,
            pid.value,
        )
        if not handle:
            return ''

        try:
            size = self.wintypes.DWORD(1024)
            buffer = self.ctypes.create_unicode_buffer(size.value)
            query = getattr(self.kernel32, 'QueryFullProcessImageNameW', None)
            if query and query(handle, 0, buffer, self.ctypes.byref(size)):
                return buffer.value
        finally:
            self.kernel32.CloseHandle(handle)

        return ''

    def find_windows_by_title(self, keywords):
        if (
            not self.is_available
            or not self.user32
            or not self.enum_windows_proc_cls
        ):
            return []

        results = []
        lowered_keywords = [keyword.lower() for keyword in keywords]

        def callback(hwnd, _lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self.get_window_title(hwnd)
            if title and any(keyword in title.lower() for keyword in lowered_keywords):
                rect = self.get_window_rect(hwnd)
                if rect:
                    results.append({'hwnd': hwnd, 'title': title, 'frame': rect})
            return True

        self.user32.EnumWindows(self.enum_windows_proc_cls(callback), 0)
        return results
