"""Win32 native overlay paint helpers."""

from .overlay_corner_geometry import overlay_corner_geometry


def paint_native_overlay(
    hdc,
    overlay_geometry,
    *,
    draw_wheel_fn,
    has_dot_window,
    hovered,
    transparent_color_ref,
    gdi32,
    user32,
    ctypes_module,
    rect_cls,
    corner_length,
    corner_width,
    corner_inset,
    active_color,
    inactive_color,
    colorref_from_hex_fn,
    ps_solid,
):
    _, _, w, h = overlay_geometry
    inset, outer = overlay_corner_geometry(
        w,
        h,
        corner_length,
        corner_width,
        corner_inset,
    )

    rect = rect_cls(0, 0, w, h)
    brush = gdi32.CreateSolidBrush(transparent_color_ref)
    if brush:
        try:
            user32.FillRect(hdc, ctypes_module.byref(rect), brush)
        finally:
            gdi32.DeleteObject(brush)

    draw_native_corners(
        hdc,
        width=w,
        height=h,
        inset=inset,
        outer=outer,
        corner_width=corner_width,
        color=active_color if hovered else inactive_color,
        gdi32=gdi32,
        colorref_from_hex_fn=colorref_from_hex_fn,
        ps_solid=ps_solid,
    )


def draw_native_filled_ellipse(
    hdc,
    cx,
    cy,
    radius,
    fill_color,
    outline_color,
    *,
    outline_width=1,
    gdi32,
    colorref_from_hex_fn,
    ps_solid,
):
    brush = gdi32.CreateSolidBrush(colorref_from_hex_fn(fill_color))
    pen = gdi32.CreatePen(
        ps_solid,
        max(1, int(round(outline_width))),
        colorref_from_hex_fn(outline_color),
    )
    if not brush or not pen:
        if brush:
            gdi32.DeleteObject(brush)
        if pen:
            gdi32.DeleteObject(pen)
        return

    old_brush = gdi32.SelectObject(hdc, brush)
    old_pen = gdi32.SelectObject(hdc, pen)
    try:
        gdi32.Ellipse(
            hdc,
            int(round(cx - radius)),
            int(round(cy - radius)),
            int(round(cx + radius)),
            int(round(cy + radius)),
        )
    finally:
        if old_brush:
            gdi32.SelectObject(hdc, old_brush)
        if old_pen:
            gdi32.SelectObject(hdc, old_pen)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)


def draw_native_corners(
    hdc,
    *,
    width,
    height,
    inset,
    outer,
    corner_width,
    color,
    gdi32,
    colorref_from_hex_fn,
    ps_solid,
):
    pen = gdi32.CreatePen(ps_solid, corner_width, colorref_from_hex_fn(color))
    if not pen:
        return

    old_pen = gdi32.SelectObject(hdc, pen)
    try:
        gdi32.MoveToEx(hdc, inset, outer, None)
        gdi32.LineTo(hdc, inset, inset)
        gdi32.LineTo(hdc, outer, inset)

        gdi32.MoveToEx(hdc, width - outer, inset, None)
        gdi32.LineTo(hdc, width - inset, inset)
        gdi32.LineTo(hdc, width - inset, outer)

        gdi32.MoveToEx(hdc, inset, height - outer, None)
        gdi32.LineTo(hdc, inset, height - inset)
        gdi32.LineTo(hdc, outer, height - inset)

        gdi32.MoveToEx(hdc, width - outer, height - inset, None)
        gdi32.LineTo(hdc, width - inset, height - inset)
        gdi32.LineTo(hdc, width - inset, height - outer)
    finally:
        if old_pen:
            gdi32.SelectObject(hdc, old_pen)
        gdi32.DeleteObject(pen)


def redraw_native_overlay_window(
    native_hwnd,
    *,
    native_use_per_pixel_alpha,
    redraw_native_alpha_fn,
    redraw_native_dot_fn,
    paint_native_fn,
    user32,
    transparent_color_ref,
    lwa_colorkey,
):
    if not native_hwnd:
        return

    if native_use_per_pixel_alpha:
        redraw_native_dot_fn()
        if redraw_native_alpha_fn():
            return
        user32.SetLayeredWindowAttributes(
            native_hwnd,
            transparent_color_ref,
            255,
            lwa_colorkey,
        )

    hdc = user32.GetDC(native_hwnd)
    if not hdc:
        return
    try:
        paint_native_fn(hdc)
    finally:
        user32.ReleaseDC(native_hwnd, hdc)
    user32.InvalidateRect(native_hwnd, None, False)
    user32.UpdateWindow(native_hwnd)


__all__ = [
    'draw_native_corners',
    'draw_native_filled_ellipse',
    'paint_native_overlay',
    'redraw_native_overlay_window',
]
