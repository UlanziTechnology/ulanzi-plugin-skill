"""PyQt overlay paint helpers."""


from .overlay_corner_geometry import overlay_corner_geometry


def draw_pyqt_smooth_dot(
    painter,
    px,
    py,
    radius,
    color,
    *,
    q_color_cls,
    q_svg_renderer_cls,
    q_byte_array_cls,
    q_rectf_cls,
    q_painter_cls,
    svg_template,
):
    svg_color = q_color_cls(color).name(q_color_cls.HexRgb)
    svg_data = svg_template.format(color=svg_color).encode('utf-8')
    renderer = q_svg_renderer_cls(q_byte_array_cls(svg_data))
    size = radius * 2
    target_rect = q_rectf_cls(round(px - radius), round(py - radius), size, size)
    painter.setRenderHint(q_painter_cls.Antialiasing, True)
    renderer.render(painter, target_rect)


def draw_pyqt_wheel_state(
    painter,
    wheel,
    *,
    wheel_dot_radius,
    q_color_cls,
    q_svg_renderer_cls,
    q_byte_array_cls,
    q_rectf_cls,
    q_painter_cls,
    svg_template,
):
    if not wheel:
        return

    draw_pyqt_smooth_dot(
        painter,
        wheel['px'],
        wheel['py'],
        wheel_dot_radius,
        wheel['color'],
        q_color_cls=q_color_cls,
        q_svg_renderer_cls=q_svg_renderer_cls,
        q_byte_array_cls=q_byte_array_cls,
        q_rectf_cls=q_rectf_cls,
        q_painter_cls=q_painter_cls,
        svg_template=svg_template,
    )


def paint_qt_overlay(
    widget,
    wheel,
    *,
    hovered,
    pyqt_available,
    q_painter_cls,
    q_color_cls,
    q_pen_cls,
    q_svg_renderer_cls,
    q_byte_array_cls,
    q_rectf_cls,
    qt_cls,
    wheel_dot_radius,
    dot_svg_template,
    corner_length,
    corner_width,
    corner_inset,
    active_color,
    inactive_color,
):
    if not pyqt_available:
        return

    painter = q_painter_cls(widget)
    painter.setRenderHint(q_painter_cls.Antialiasing)
    draw_pyqt_wheel_state(
        painter,
        wheel,
        wheel_dot_radius=wheel_dot_radius,
        q_color_cls=q_color_cls,
        q_svg_renderer_cls=q_svg_renderer_cls,
        q_byte_array_cls=q_byte_array_cls,
        q_rectf_cls=q_rectf_cls,
        q_painter_cls=q_painter_cls,
        svg_template=dot_svg_template,
    )

    width = widget.width()
    height = widget.height()
    color = q_color_cls(active_color if hovered else inactive_color)
    pen = q_pen_cls(color, corner_width)
    pen.setCapStyle(qt_cls.SquareCap)
    pen.setJoinStyle(qt_cls.MiterJoin)
    painter.setPen(pen)
    inset, outer = overlay_corner_geometry(
        width,
        height,
        corner_length,
        corner_width,
        corner_inset,
    )

    painter.drawLine(inset, outer, inset, inset)
    painter.drawLine(inset, inset, outer, inset)
    painter.drawLine(width - outer, inset, width - inset, inset)
    painter.drawLine(width - inset, inset, width - inset, outer)
    painter.drawLine(inset, height - outer, inset, height - inset)
    painter.drawLine(inset, height - inset, outer, height - inset)
    painter.drawLine(width - outer, height - inset, width - inset, height - inset)
    painter.drawLine(width - inset, height - inset, width - inset, height - outer)


__all__ = [
    'draw_pyqt_smooth_dot',
    'draw_pyqt_wheel_state',
    'paint_qt_overlay',
]
