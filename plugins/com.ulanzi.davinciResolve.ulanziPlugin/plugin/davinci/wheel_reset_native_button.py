"""Native reset-button click path for DaVinci wheel reset actions."""

import math
import time

from .wheel_reset_geometry import wheel_reset_button_point


def reset_wheel_via_native_button(
    area,
    state_callbacks,
    detect_wheel_circle_in_area_fn,
    mouse_click_fn,
    get_cursor_position_fn,
    set_cursor_position_fn=None,
    commit_state=True,
):
    reset_x, reset_y = wheel_reset_button_point(area)
    original_x, original_y = get_cursor_position_fn()

    if not mouse_click_fn(reset_x, reset_y):
        return False

    if set_cursor_position_fn:
        set_cursor_position_fn(int(round(original_x)), int(round(original_y)))

    area_name = area['name']
    if not commit_state:
        print(f"clicked {area_name} native reset button pending verify: ({reset_x:.0f}, {reset_y:.0f})")
        return True

    wheel_geometry = detect_wheel_circle_in_area_fn(area)
    center_x = (
        wheel_geometry['wheel_center_x']
        if wheel_geometry
        else area.get('center_x', area['x'] + area['w'] / 2)
    )
    center_y = (
        wheel_geometry['wheel_center_y']
        if wheel_geometry
        else area.get('center_y', area['y'] + area['h'] / 2)
    )

    state_callbacks['commit_wheel_center_reset_state_fn'](
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_geometry['wheel_radius'] if wheel_geometry else min(area['w'], area['h']) / 2,
        angle=-math.pi / 2,
        updated_at=time.time(),
    )
    print(f"clicked {area_name} native reset button: ({reset_x:.0f}, {reset_y:.0f})")
    return True


__all__ = ['reset_wheel_via_native_button']
