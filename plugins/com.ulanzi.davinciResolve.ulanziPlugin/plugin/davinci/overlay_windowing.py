"""Overlay window creation and window-style helpers."""

import math


def create_tk_overlay(root, *, tk_module, tk_error_cls, transparent_color):
    if not root:
        return None, None

    window = tk_module.Toplevel(root)
    window.withdraw()
    window.overrideredirect(True)
    window.attributes('-topmost', True)

    window.configure(bg=transparent_color)
    try:
        window.attributes('-transparentcolor', transparent_color)
    except tk_error_cls:
        window.attributes('-alpha', 0.35)

    canvas = tk_module.Canvas(
        window,
        bg=transparent_color,
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(fill='both', expand=True)
    return window, canvas


def apply_tk_click_through(
    tk_window,
    *,
    is_windows,
    win32_available,
    get_window_long_fn,
    set_window_long_fn,
    user32,
    transparent_color_ref,
    gwl_exstyle,
    ws_ex_layered,
    ws_ex_transparent,
    ws_ex_topmost,
    ws_ex_toolwindow,
    ws_ex_noactivate,
    lwa_colorkey,
    hwnd_topmost,
    swp_nomove,
    swp_nosize,
    swp_noactivate,
):
    if not (is_windows and win32_available and tk_window):
        return

    try:
        tk_window.update_idletasks()
        hwnd = tk_window.winfo_id()
        style = get_window_long_fn(hwnd, gwl_exstyle)
        style |= ws_ex_layered | ws_ex_transparent | ws_ex_topmost | ws_ex_toolwindow | ws_ex_noactivate
        set_window_long_fn(hwnd, gwl_exstyle, style)
        user32.SetLayeredWindowAttributes(hwnd, transparent_color_ref, 255, lwa_colorkey)
        user32.SetWindowPos(
            hwnd,
            hwnd_topmost,
            0,
            0,
            0,
            0,
            swp_nomove | swp_nosize | swp_noactivate,
        )
    except Exception:
        pass


def create_native_dot_window(
    *,
    native_use_per_pixel_alpha,
    dot_radius,
    user32,
    kernel32,
    class_name,
    ws_ex_layered,
    ws_ex_transparent,
    ws_ex_topmost,
    ws_ex_toolwindow,
    ws_ex_noactivate,
    ws_popup,
    sw_hide,
):
    if not native_use_per_pixel_alpha:
        return None

    dot_size = max(1, int(math.ceil(dot_radius * 2 + 2)))
    ex_style = ws_ex_layered | ws_ex_transparent | ws_ex_topmost | ws_ex_toolwindow | ws_ex_noactivate
    hwnd = user32.CreateWindowExW(
        ex_style,
        class_name,
        '',
        ws_popup,
        0,
        0,
        dot_size,
        dot_size,
        None,
        None,
        kernel32.GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        return None
    user32.ShowWindow(hwnd, sw_hide)
    return hwnd


def create_native_overlay_window(
    overlay_geometry,
    *,
    owner,
    instances,
    ensure_class_fn,
    native_use_per_pixel_alpha,
    dot_radius,
    transparent_color_ref,
    user32,
    kernel32,
    class_name,
    ws_ex_layered,
    ws_ex_transparent,
    ws_ex_topmost,
    ws_ex_toolwindow,
    ws_ex_noactivate,
    ws_popup,
    lwa_colorkey,
    sw_hide,
):
    if not ensure_class_fn():
        return None, None, False

    x, y, w, h = overlay_geometry
    ex_style = ws_ex_layered | ws_ex_transparent | ws_ex_topmost | ws_ex_toolwindow | ws_ex_noactivate
    hwnd = user32.CreateWindowExW(
        ex_style,
        class_name,
        '',
        ws_popup,
        x,
        y,
        w,
        h,
        None,
        None,
        kernel32.GetModuleHandleW(None),
        None,
    )
    if not hwnd:
        return None, None, True

    instances[int(hwnd)] = owner
    dot_hwnd = create_native_dot_window(
        native_use_per_pixel_alpha=native_use_per_pixel_alpha,
        dot_radius=dot_radius,
        user32=user32,
        kernel32=kernel32,
        class_name=class_name,
        ws_ex_layered=ws_ex_layered,
        ws_ex_transparent=ws_ex_transparent,
        ws_ex_topmost=ws_ex_topmost,
        ws_ex_toolwindow=ws_ex_toolwindow,
        ws_ex_noactivate=ws_ex_noactivate,
        ws_popup=ws_popup,
        sw_hide=sw_hide,
    )
    if not native_use_per_pixel_alpha:
        user32.SetLayeredWindowAttributes(hwnd, transparent_color_ref, 255, lwa_colorkey)
    user32.ShowWindow(hwnd, sw_hide)
    return hwnd, dot_hwnd, False


def setup_qt_overlay_window(
    widget,
    *,
    update_geometry_fn,
    sys_platform,
    qt_cls,
    c_void_p_cls,
):
    flags = qt_cls.FramelessWindowHint | qt_cls.Tool | qt_cls.WindowStaysOnTopHint
    if hasattr(qt_cls, 'WindowDoesNotAcceptFocus'):
        flags |= qt_cls.WindowDoesNotAcceptFocus
    widget.setWindowFlags(flags)
    widget.setAttribute(qt_cls.WA_TranslucentBackground)
    widget.setAttribute(qt_cls.WA_TransparentForMouseEvents)
    if hasattr(qt_cls, 'WA_ShowWithoutActivating'):
        widget.setAttribute(qt_cls.WA_ShowWithoutActivating)
    if sys_platform == 'darwin' and hasattr(qt_cls, 'WA_MacAlwaysShowToolWindow'):
        widget.setAttribute(qt_cls.WA_MacAlwaysShowToolWindow)

    update_geometry_fn()

    if sys_platform == 'darwin':
        try:
            if c_void_p_cls is None:
                raise RuntimeError('ctypes.c_void_p is unavailable')

            import objc
            from AppKit import (
                NSColor,
                NSFloatingWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowCollectionBehaviorIgnoresCycle,
            )

            # winId() creates the native NSView without briefly activating the
            # separate Python helper application.
            ns_view = objc.objc_object(c_void_p=c_void_p_cls(int(widget.winId())))
            ns_window = ns_view.window()
            if not ns_window:
                raise RuntimeError('unable to resolve the native NSWindow')

            ns_window.setLevel_(NSFloatingWindowLevel)
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
                | NSWindowCollectionBehaviorIgnoresCycle
            )
            ns_window.setHidesOnDeactivate_(False)
            ns_window.setIgnoresMouseEvents_(True)
            ns_window.setOpaque_(False)
            ns_window.setBackgroundColor_(NSColor.clearColor())
            ns_window.setHasShadow_(False)
            widget._mac_ns_window = ns_window
            widget.hide()
        except Exception as e:
            print(f"macOS window setup failed: {e}")
            widget._mac_ns_window = None
            widget.hide()
    else:
        widget.hide()


def initialize_overlay_backend(
    *,
    force_win32_native,
    is_windows,
    win32_available,
    tkinter_available,
    win32_overlay_available,
    pyqt_available,
    init_native_fn,
    native_ready_fn,
    init_tk_fn,
    setup_qt_fn,
):
    if force_win32_native and is_windows and win32_available:
        init_native_fn()
        if native_ready_fn():
            return

    if not pyqt_available and is_windows and tkinter_available:
        init_tk_fn()
        return

    if not pyqt_available and is_windows and win32_overlay_available:
        init_native_fn()
        return

    if not pyqt_available:
        return

    return setup_qt_fn()


__all__ = [
    'apply_tk_click_through',
    'create_native_dot_window',
    'create_native_overlay_window',
    'create_tk_overlay',
    'initialize_overlay_backend',
    'setup_qt_overlay_window',
]
