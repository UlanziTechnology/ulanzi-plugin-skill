"""Win32 per-pixel-alpha overlay paint helpers."""

import math

from .overlay_corner_geometry import overlay_corner_geometry


def redraw_native_alpha_dot(
    hwnd,
    wheel,
    overlay_geometry,
    *,
    dot_hidden,
    native_visible,
    gdiplus_ready,
    gdiplus,
    gdi32,
    user32,
    ctypes_module,
    bitmap_info_cls,
    bitmap_info_header_cls,
    point_cls,
    size_cls,
    blend_function_cls,
    argb_from_hex_fn,
    dot_radius,
    bi_rgb,
    dib_rgb_colors,
    smoothing_mode,
    pixel_offset_mode,
    ac_src_over,
    ac_src_alpha,
    ulw_alpha,
    sw_hide,
    sw_shownoactivate,
    hwnd_topmost,
    swp_noactivate,
    swp_showwindow,
):
    if not hwnd or not gdiplus_ready or dot_hidden or not native_visible:
        if hwnd:
            user32.ShowWindow(hwnd, sw_hide)
        return False, False

    if not wheel:
        user32.ShowWindow(hwnd, sw_hide)
        return False, False

    overlay_x, overlay_y, _, _ = overlay_geometry
    radius = float(dot_radius)
    padding = 1.0
    size_px = max(1, int(math.ceil((radius + padding) * 2.0)))
    dot_left = int(round(overlay_x + wheel['px'] - size_px / 2.0))
    dot_top = int(round(overlay_y + wheel['py'] - size_px / 2.0))

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return False, False

    mem_dc = None
    bitmap = None
    old_bitmap = None
    graphics = ctypes_module.c_void_p()
    bits = ctypes_module.c_void_p()
    try:
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            return False, False

        bmi = bitmap_info_cls()
        bmi.bmiHeader.biSize = ctypes_module.sizeof(bitmap_info_header_cls)
        bmi.bmiHeader.biWidth = size_px
        bmi.bmiHeader.biHeight = -size_px
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = bi_rgb
        bitmap = gdi32.CreateDIBSection(
            screen_dc,
            ctypes_module.byref(bmi),
            dib_rgb_colors,
            ctypes_module.byref(bits),
            None,
            0,
        )
        if not bitmap or not bits:
            return False, False

        ctypes_module.memset(bits, 0, size_px * size_px * 4)
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

        if gdiplus.GdipCreateFromHDC(mem_dc, ctypes_module.byref(graphics)) != 0 or not graphics:
            return False, False
        gdiplus.GdipSetSmoothingMode(graphics, smoothing_mode)
        gdiplus.GdipSetPixelOffsetMode(graphics, pixel_offset_mode)

        brush = ctypes_module.c_void_p()
        if gdiplus.GdipCreateSolidFill(
            argb_from_hex_fn(wheel['color']),
            ctypes_module.byref(brush),
        ) == 0:
            try:
                gdiplus.GdipFillEllipse(
                    graphics,
                    brush,
                    ctypes_module.c_float(padding),
                    ctypes_module.c_float(padding),
                    ctypes_module.c_float(radius * 2.0),
                    ctypes_module.c_float(radius * 2.0),
                )
            finally:
                gdiplus.GdipDeleteBrush(brush)

        dst_point = point_cls(dot_left, dot_top)
        src_point = point_cls(0, 0)
        size = size_cls(size_px, size_px)
        blend = blend_function_cls(ac_src_over, 0, 255, ac_src_alpha)
        updated = bool(user32.UpdateLayeredWindow(
            hwnd,
            screen_dc,
            ctypes_module.byref(dst_point),
            ctypes_module.byref(size),
            mem_dc,
            ctypes_module.byref(src_point),
            0,
            ctypes_module.byref(blend),
            ulw_alpha,
        ))
        if updated:
            user32.ShowWindow(hwnd, sw_shownoactivate)
            user32.SetWindowPos(
                hwnd,
                hwnd_topmost,
                dot_left,
                dot_top,
                size_px,
                size_px,
                swp_noactivate | swp_showwindow,
            )
        return updated, updated
    finally:
        if graphics:
            gdiplus.GdipDeleteGraphics(graphics)
        if old_bitmap:
            gdi32.SelectObject(mem_dc, old_bitmap)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def redraw_native_alpha_overlay(
    hwnd,
    overlay_geometry,
    *,
    draw_content_fn,
    gdiplus_ready,
    gdiplus,
    gdi32,
    user32,
    ctypes_module,
    bitmap_info_cls,
    bitmap_info_header_cls,
    point_cls,
    size_cls,
    blend_function_cls,
    bi_rgb,
    dib_rgb_colors,
    smoothing_mode,
    pixel_offset_mode,
    ac_src_over,
    ac_src_alpha,
    ulw_alpha,
):
    if not hwnd or not gdiplus_ready:
        return False

    x, y, w, h = overlay_geometry
    width = int(w)
    height = int(h)
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return False

    mem_dc = None
    bitmap = None
    old_bitmap = None
    graphics = ctypes_module.c_void_p()
    bits = ctypes_module.c_void_p()
    try:
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            return False

        bmi = bitmap_info_cls()
        bmi.bmiHeader.biSize = ctypes_module.sizeof(bitmap_info_header_cls)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = bi_rgb
        bitmap = gdi32.CreateDIBSection(
            screen_dc,
            ctypes_module.byref(bmi),
            dib_rgb_colors,
            ctypes_module.byref(bits),
            None,
            0,
        )
        if not bitmap or not bits:
            return False

        ctypes_module.memset(bits, 0, width * height * 4)
        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

        if gdiplus.GdipCreateFromHDC(mem_dc, ctypes_module.byref(graphics)) != 0 or not graphics:
            return False
        gdiplus.GdipSetSmoothingMode(graphics, smoothing_mode)
        gdiplus.GdipSetPixelOffsetMode(graphics, pixel_offset_mode)

        draw_content_fn(graphics, width, height)

        dst_point = point_cls(int(x), int(y))
        src_point = point_cls(0, 0)
        size = size_cls(width, height)
        blend = blend_function_cls(ac_src_over, 0, 255, ac_src_alpha)
        return bool(user32.UpdateLayeredWindow(
            hwnd,
            screen_dc,
            ctypes_module.byref(dst_point),
            ctypes_module.byref(size),
            mem_dc,
            ctypes_module.byref(src_point),
            0,
            ctypes_module.byref(blend),
            ulw_alpha,
        ))
    finally:
        if graphics:
            gdiplus.GdipDeleteGraphics(graphics)
        if old_bitmap:
            gdi32.SelectObject(mem_dc, old_bitmap)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def draw_native_alpha_wheel_state(
    graphics,
    wheel,
    *,
    gdiplus,
    ctypes_module,
    argb_from_hex_fn,
    dot_radius,
):
    if not wheel or not gdiplus:
        return

    px = float(wheel['px'])
    py = float(wheel['py'])
    radius = float(dot_radius)
    brush = ctypes_module.c_void_p()
    if gdiplus.GdipCreateSolidFill(
        argb_from_hex_fn(wheel['color']),
        ctypes_module.byref(brush),
    ) != 0:
        return
    try:
        gdiplus.GdipFillEllipse(
            graphics,
            brush,
            ctypes_module.c_float(px - radius),
            ctypes_module.c_float(py - radius),
            ctypes_module.c_float(radius * 2.0),
            ctypes_module.c_float(radius * 2.0),
        )
    finally:
        gdiplus.GdipDeleteBrush(brush)


def draw_native_alpha_corners(
    graphics,
    *,
    width,
    height,
    hovered,
    gdiplus,
    ctypes_module,
    argb_from_hex_fn,
    corner_length,
    corner_width,
    corner_inset,
    active_color,
    inactive_color,
    gdip_unit_pixel,
):
    if not gdiplus:
        return

    inset, outer = overlay_corner_geometry(
        width,
        height,
        corner_length,
        corner_width,
        corner_inset,
    )
    color = active_color if hovered else inactive_color
    pen = ctypes_module.c_void_p()
    if gdiplus.GdipCreatePen1(
        argb_from_hex_fn(color),
        ctypes_module.c_float(float(corner_width)),
        gdip_unit_pixel,
        ctypes_module.byref(pen),
    ) != 0:
        return

    def draw_line(x1, y1, x2, y2):
        gdiplus.GdipDrawLine(
            graphics,
            pen,
            ctypes_module.c_float(float(x1)),
            ctypes_module.c_float(float(y1)),
            ctypes_module.c_float(float(x2)),
            ctypes_module.c_float(float(y2)),
        )

    try:
        draw_line(inset, outer, inset, inset)
        draw_line(inset, inset, outer, inset)
        draw_line(width - outer, inset, width - inset, inset)
        draw_line(width - inset, inset, width - inset, outer)
        draw_line(inset, height - outer, inset, height - inset)
        draw_line(inset, height - inset, outer, height - inset)
        draw_line(width - outer, height - inset, width - inset, height - inset)
        draw_line(width - inset, height - inset, width - inset, height - outer)
    finally:
        gdiplus.GdipDeletePen(pen)


__all__ = [
    'draw_native_alpha_corners',
    'draw_native_alpha_wheel_state',
    'redraw_native_alpha_dot',
    'redraw_native_alpha_overlay',
]
