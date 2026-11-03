"""Windows native API declarations used by input, capture, and overlays."""

import ctypes
import platform


AVAILABLE = platform.system() == 'Windows' and hasattr(ctypes, 'windll')
user32 = None
gdi32 = None
kernel32 = None
gdiplus = None
wintypes = None

POINT = None
SIZE = None
RECT = None
BITMAPINFOHEADER = None
BITMAPINFO = None
BLENDFUNCTION = None
GdiplusStartupInput = None
EnumWindowsProc = None
WNDPROC = None
WNDCLASS = None
PAINTSTRUCT = None
MSG = None
MOUSEINPUT = None
INPUT = None
get_window_long = None
set_window_long = None

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
HWND_TOPMOST = -1
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
LWA_COLORKEY = 0x00000001
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
PS_SOLID = 0
PM_REMOVE = 0x0001
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
VK_LBUTTON = 0x01
INPUT_MOUSE = 0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
BI_RGB = 0
DIB_RGB_COLORS = 0
GDIP_UNIT_PIXEL = 2
GDIP_SMOOTHING_MODE_ANTIALIAS = 4
GDIP_PIXEL_OFFSET_MODE_HALF = 4


if AVAILABLE:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    try:
        gdiplus = ctypes.windll.gdiplus
    except Exception:
        gdiplus = None

    class POINT(ctypes.Structure):
        _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [('cx', wintypes.LONG), ('cy', wintypes.LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [
            ('left', wintypes.LONG),
            ('top', wintypes.LONG),
            ('right', wintypes.LONG),
            ('bottom', wintypes.LONG),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', wintypes.DWORD),
            ('biWidth', wintypes.LONG),
            ('biHeight', wintypes.LONG),
            ('biPlanes', wintypes.WORD),
            ('biBitCount', wintypes.WORD),
            ('biCompression', wintypes.DWORD),
            ('biSizeImage', wintypes.DWORD),
            ('biXPelsPerMeter', wintypes.LONG),
            ('biYPelsPerMeter', wintypes.LONG),
            ('biClrUsed', wintypes.DWORD),
            ('biClrImportant', wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [
            ('rgbBlue', ctypes.c_byte),
            ('rgbGreen', ctypes.c_byte),
            ('rgbRed', ctypes.c_byte),
            ('rgbReserved', ctypes.c_byte),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ('bmiHeader', BITMAPINFOHEADER),
            ('bmiColors', RGBQUAD * 1),
        ]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ('BlendOp', ctypes.c_byte),
            ('BlendFlags', ctypes.c_byte),
            ('SourceConstantAlpha', ctypes.c_byte),
            ('AlphaFormat', ctypes.c_byte),
        ]

    class GdiplusStartupInput(ctypes.Structure):
        _fields_ = [
            ('GdiplusVersion', wintypes.UINT),
            ('DebugEventCallback', ctypes.c_void_p),
            ('SuppressBackgroundThread', wintypes.BOOL),
            ('SuppressExternalCodecs', wintypes.BOOL),
        ]

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    LRESULT = wintypes.LPARAM
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ('hdc', wintypes.HDC),
            ('fErase', wintypes.BOOL),
            ('rcPaint', RECT),
            ('fRestore', wintypes.BOOL),
            ('fIncUpdate', wintypes.BOOL),
            ('rgbReserved', ctypes.c_byte * 32),
        ]

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ('style', wintypes.UINT),
            ('lpfnWndProc', WNDPROC),
            ('cbClsExtra', ctypes.c_int),
            ('cbWndExtra', ctypes.c_int),
            ('hInstance', wintypes.HINSTANCE),
            ('hIcon', wintypes.HICON),
            ('hCursor', wintypes.HCURSOR),
            ('hbrBackground', wintypes.HBRUSH),
            ('lpszMenuName', wintypes.LPCWSTR),
            ('lpszClassName', wintypes.LPCWSTR),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('message', wintypes.UINT),
            ('wParam', wintypes.WPARAM),
            ('lParam', wintypes.LPARAM),
            ('time', wintypes.DWORD),
            ('pt', POINT),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ('dx', wintypes.LONG),
            ('dy', wintypes.LONG),
            ('mouseData', wintypes.DWORD),
            ('dwFlags', wintypes.DWORD),
            ('time', wintypes.DWORD),
            ('dwExtraInfo', ctypes.c_size_t),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [('mi', MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('union', INPUT_UNION)]

    get_window_long = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
    set_window_long = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.FillRect.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.HBRUSH,
    ]
    user32.FillRect.restype = ctypes.c_int
    user32.InvalidateRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(RECT),
        wintypes.BOOL,
    ]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    user32.mouse_event.restype = None
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.COLORREF,
        ctypes.c_byte,
        wintypes.DWORD,
    ]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND,
        wintypes.HDC,
        ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE),
        wintypes.HDC,
        ctypes.POINTER(POINT),
        wintypes.COLORREF,
        ctypes.POINTER(BLENDFUNCTION),
        wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.MoveToEx.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.LPVOID,
    ]
    gdi32.MoveToEx.restype = wintypes.BOOL
    gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.LineTo.restype = wintypes.BOOL
    gdi32.Ellipse.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.Ellipse.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    if gdiplus:
        gdiplus.GdiplusStartup.argtypes = [
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(GdiplusStartupInput),
            ctypes.c_void_p,
        ]
        gdiplus.GdiplusStartup.restype = ctypes.c_int
        gdiplus.GdiplusShutdown.argtypes = [ctypes.c_size_t]
        gdiplus.GdiplusShutdown.restype = None
        gdiplus.GdipCreateFromHDC.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        gdiplus.GdipCreateFromHDC.restype = ctypes.c_int
        gdiplus.GdipDeleteGraphics.argtypes = [ctypes.c_void_p]
        gdiplus.GdipDeleteGraphics.restype = ctypes.c_int
        gdiplus.GdipSetSmoothingMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdiplus.GdipSetSmoothingMode.restype = ctypes.c_int
        gdiplus.GdipSetPixelOffsetMode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        gdiplus.GdipSetPixelOffsetMode.restype = ctypes.c_int
        gdiplus.GdipCreateSolidFill.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        gdiplus.GdipCreateSolidFill.restype = ctypes.c_int
        gdiplus.GdipDeleteBrush.argtypes = [ctypes.c_void_p]
        gdiplus.GdipDeleteBrush.restype = ctypes.c_int
        gdiplus.GdipFillEllipse.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        gdiplus.GdipFillEllipse.restype = ctypes.c_int
        gdiplus.GdipCreatePen1.argtypes = [
            wintypes.DWORD,
            ctypes.c_float,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        gdiplus.GdipCreatePen1.restype = ctypes.c_int
        gdiplus.GdipDeletePen.argtypes = [ctypes.c_void_p]
        gdiplus.GdipDeletePen.restype = ctypes.c_int
        gdiplus.GdipDrawLine.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        gdiplus.GdipDrawLine.restype = ctypes.c_int

    try:
        set_dpi_awareness_context = getattr(
            user32,
            'SetProcessDpiAwarenessContext',
            None,
        )
        if set_dpi_awareness_context:
            set_dpi_awareness_context(ctypes.c_void_p(-4))
        else:
            user32.SetProcessDPIAware()
    except Exception:
        pass
