"""Tk overlay paint helpers."""

from .overlay_corner_geometry import overlay_corner_geometry


def redraw_tk_overlay(
    canvas,
    overlay_geometry,
    wheel,
    *,
    hovered,
    wheel_dot_radius,
    corner_length,
    corner_width,
    corner_inset,
    active_color,
    inactive_color,
):
    if not canvas:
        return

    canvas.delete('all')

    if wheel:
        px = wheel['px']
        py = wheel['py']
        dot_radius = wheel_dot_radius
        canvas.create_oval(
            px - dot_radius,
            py - dot_radius,
            px + dot_radius,
            py + dot_radius,
            fill=wheel['color'],
            outline='',
            width=0,
        )

    _, _, w, h = overlay_geometry
    color = active_color if hovered else inactive_color
    inset, outer = overlay_corner_geometry(
        w,
        h,
        corner_length,
        corner_width,
        corner_inset,
    )

    line_opts = {
        'fill': color,
        'width': corner_width,
        'capstyle': 'butt',
        'joinstyle': 'miter',
    }

    canvas.create_line(inset, outer, inset, inset, outer, inset, **line_opts)
    canvas.create_line(w - outer, inset, w - inset, inset, w - inset, outer, **line_opts)
    canvas.create_line(inset, h - outer, inset, h - inset, outer, h - inset, **line_opts)
    canvas.create_line(w - outer, h - inset, w - inset, h - inset, w - inset, h - outer, **line_opts)


__all__ = ['redraw_tk_overlay']
