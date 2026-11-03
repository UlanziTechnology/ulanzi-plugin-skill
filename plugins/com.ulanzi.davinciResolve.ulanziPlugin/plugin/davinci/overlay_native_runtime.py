"""Win32 native overlay runtime state."""


class OverlayNativeRuntime:
    def __init__(
        self,
        *,
        is_windows,
        win32_available,
        user32,
        kernel32,
        ctypes_module,
        wndproc_cls,
        wndclass_cls,
        paintstruct_cls,
        gdiplus,
        gdiplus_startup_input_cls,
        class_name,
        wm_nchittest,
        httransparent,
        wm_erasebkgnd,
        wm_paint,
        cs_hredraw,
        cs_vredraw,
    ):
        self.is_windows = is_windows
        self.win32_available = win32_available
        self.user32 = user32
        self.kernel32 = kernel32
        self.ctypes = ctypes_module
        self.wndproc_cls = wndproc_cls
        self.wndclass_cls = wndclass_cls
        self.paintstruct_cls = paintstruct_cls
        self.gdiplus = gdiplus
        self.gdiplus_startup_input_cls = gdiplus_startup_input_cls
        self.class_name = class_name
        self.wm_nchittest = wm_nchittest
        self.httransparent = httransparent
        self.wm_erasebkgnd = wm_erasebkgnd
        self.wm_paint = wm_paint
        self.cs_hredraw = cs_hredraw
        self.cs_vredraw = cs_vredraw
        self.instances = {}
        self._class_registered = False
        self._wndproc_ref = None
        self._gdiplus_token = (
            ctypes_module.c_size_t(0)
            if is_windows and win32_available and ctypes_module is not None
            else None
        )

    def window_proc(self, hwnd, msg, wparam, lparam):
        if msg == self.wm_nchittest:
            return self.httransparent
        if msg == self.wm_erasebkgnd:
            return 1
        if msg == self.wm_paint:
            ps = self.paintstruct_cls()
            hdc = self.user32.BeginPaint(hwnd, self.ctypes.byref(ps))
            try:
                overlay = self.instances.get(int(hwnd))
                if overlay:
                    overlay._paint_native(hdc)
            finally:
                self.user32.EndPaint(hwnd, self.ctypes.byref(ps))
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def ensure_class(self):
        if not (self.is_windows and self.win32_available):
            return False
        if self._class_registered:
            return True
        if not (self.user32 and self.kernel32 and self.wndproc_cls and self.wndclass_cls):
            return False

        self._wndproc_ref = self.wndproc_cls(self.window_proc)
        wnd_class = self.wndclass_cls()
        wnd_class.style = self.cs_hredraw | self.cs_vredraw
        wnd_class.lpfnWndProc = self._wndproc_ref
        wnd_class.hInstance = self.kernel32.GetModuleHandleW(None)
        wnd_class.lpszClassName = self.class_name
        atom = self.user32.RegisterClassW(self.ctypes.byref(wnd_class))
        if not atom:
            return False
        self._class_registered = True
        return True

    def ensure_gdiplus(self):
        if not (self.is_windows and self.win32_available and self.gdiplus):
            return False
        if not self.ctypes or not self.gdiplus_startup_input_cls or self._gdiplus_token is None:
            return False
        if self._gdiplus_token.value:
            return True

        startup_input = self.gdiplus_startup_input_cls()
        startup_input.GdiplusVersion = 1
        startup_input.DebugEventCallback = None
        startup_input.SuppressBackgroundThread = False
        startup_input.SuppressExternalCodecs = False
        status = self.gdiplus.GdiplusStartup(
            self.ctypes.byref(self._gdiplus_token),
            self.ctypes.byref(startup_input),
            None,
        )
        return status == 0


__all__ = ['OverlayNativeRuntime']
