"""Overlay window visibility and teardown helpers."""


def refresh_overlay_surface(
    *,
    tk_canvas,
    native_hwnd,
    redraw_tk_fn,
    redraw_native_fn,
    update_qt_fn,
):
    if tk_canvas:
        redraw_tk_fn()
        return
    if native_hwnd:
        redraw_native_fn()
        return
    update_qt_fn()


def update_overlay_geometry(
    overlay_geometry,
    *,
    tk_window,
    tk_canvas,
    native_hwnd,
    native_visible,
    redraw_tk_fn,
    redraw_native_fn,
    set_geometry_fn,
    user32,
    hwnd_topmost,
    swp_noactivate,
    swp_showwindow,
):
    x, y, w, h = overlay_geometry
    if tk_window:
        tk_window.geometry(f'{w}x{h}+{x}+{y}')
        if tk_canvas:
            tk_canvas.configure(width=w, height=h)
            redraw_tk_fn()
        return

    if native_hwnd:
        user32.SetWindowPos(
            native_hwnd,
            hwnd_topmost,
            x,
            y,
            w,
            h,
            swp_noactivate | (swp_showwindow if native_visible else 0),
        )
        redraw_native_fn()
        return

    set_geometry_fn(x, y, w, h)


def hide_native_dot_window(native_dot_hwnd, *, user32, sw_hide):
    if not native_dot_hwnd:
        return False
    user32.ShowWindow(native_dot_hwnd, sw_hide)
    return True


def show_tk_overlay(
    tk_window,
    *,
    update_geometry_fn,
    apply_click_through_fn,
    user32,
    hwnd_topmost,
    sw_shownoactivate,
    swp_nomove,
    swp_nosize,
    swp_noactivate,
    swp_showwindow,
):
    if not tk_window:
        return False

    update_geometry_fn()
    tk_window.deiconify()
    tk_window.update_idletasks()
    apply_click_through_fn()
    hwnd = tk_window.winfo_id()
    user32.ShowWindow(hwnd, sw_shownoactivate)
    user32.SetWindowPos(
        hwnd,
        hwnd_topmost,
        0,
        0,
        0,
        0,
        swp_nomove | swp_nosize | swp_noactivate | swp_showwindow,
    )
    return True


def show_native_overlay(
    native_hwnd,
    *,
    update_geometry_fn,
    redraw_native_fn,
    user32,
    hwnd_topmost,
    sw_shownoactivate,
    swp_nomove,
    swp_nosize,
    swp_noactivate,
    swp_showwindow,
):
    if not native_hwnd:
        return False

    update_geometry_fn()
    user32.ShowWindow(native_hwnd, sw_shownoactivate)
    user32.SetWindowPos(
        native_hwnd,
        hwnd_topmost,
        0,
        0,
        0,
        0,
        swp_nomove | swp_nosize | swp_noactivate | swp_showwindow,
    )
    redraw_native_fn()
    return True


def hide_tk_overlay(tk_window, *, user32, sw_hide):
    if not tk_window:
        return False

    try:
        user32.ShowWindow(tk_window.winfo_id(), sw_hide)
    except Exception:
        tk_window.withdraw()
    return False


def hide_native_overlay(native_hwnd, native_dot_hwnd, *, user32, sw_hide):
    if not native_hwnd:
        return False, False

    user32.ShowWindow(native_hwnd, sw_hide)
    if native_dot_hwnd:
        user32.ShowWindow(native_dot_hwnd, sw_hide)
    return False, False


def delete_tk_overlay(tk_window, tk_canvas, *, tk_error_cls):
    if not tk_window:
        return tk_window, tk_canvas

    try:
        tk_window.destroy()
    except tk_error_cls:
        pass
    return None, None


def delete_native_overlay(
    native_hwnd,
    native_dot_hwnd,
    *,
    instances,
    user32,
    sw_hide,
):
    if not native_hwnd:
        return native_hwnd, native_dot_hwnd, False, False

    if native_dot_hwnd:
        user32.ShowWindow(native_dot_hwnd, sw_hide)
        user32.DestroyWindow(native_dot_hwnd)
        native_dot_hwnd = None

    instances.pop(int(native_hwnd), None)
    user32.DestroyWindow(native_hwnd)
    return None, native_dot_hwnd, False, False


__all__ = [
    'delete_native_overlay',
    'delete_tk_overlay',
    'hide_native_overlay',
    'hide_native_dot_window',
    'hide_tk_overlay',
    'refresh_overlay_surface',
    'show_native_overlay',
    'show_tk_overlay',
    'update_overlay_geometry',
]
