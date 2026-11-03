"""Geometry helpers for wheel reset actions."""


def wheel_reset_button_point(area):
    label_frame = area.get('label_frame')
    if label_frame:
        _label_x, label_y, _label_w, label_h = label_frame
        reset_y = label_y + label_h / 2
    else:
        reset_y = area['y'] - max(10, min(18, area['h'] * 0.08))

    reset_x = area['x'] + area['w'] - max(8, min(18, area['w'] * 0.06))
    return reset_x, reset_y


__all__ = ['wheel_reset_button_point']
