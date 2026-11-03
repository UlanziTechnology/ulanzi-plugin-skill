"""Wheel reset actions kept outside the main manager."""

import math
import time

from .wheel_reset_geometry import wheel_reset_button_point
from .wheel_reset_native_button import reset_wheel_via_native_button


def _wheel_center_from_handle_or_area(area, handle, detect_wheel_circle_in_area_fn):
    wheel_geometry = None
    if not handle or 'wheel_center_x' not in handle or 'wheel_center_y' not in handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        if handle and wheel_geometry:
            handle.update(wheel_geometry)

    center_x = (
        handle.get('wheel_center_x')
        if handle and handle.get('wheel_center_x') is not None
        else (
            wheel_geometry['wheel_center_x']
            if wheel_geometry
            else area.get('center_x', area['x'] + area['w'] / 2)
        )
    )
    center_y = (
        handle.get('wheel_center_y')
        if handle and handle.get('wheel_center_y') is not None
        else (
            wheel_geometry['wheel_center_y']
            if wheel_geometry
            else area.get('center_y', area['y'] + area['h'] / 2)
        )
    )
    wheel_radius = (
        handle.get('wheel_radius')
        if handle and handle.get('wheel_radius') is not None
        else (
            wheel_geometry['wheel_radius']
            if wheel_geometry
            else min(area['w'], area['h']) / 2
        )
    )
    return center_x, center_y, wheel_radius


def _handle_distance_from_center(area, handle, detect_wheel_circle_in_area_fn):
    center_x, center_y, wheel_radius = _wheel_center_from_handle_or_area(
        area,
        handle,
        detect_wheel_circle_in_area_fn,
    )
    start_x = handle.get('x', center_x) if handle else center_x
    start_y = handle.get('y', center_y) if handle else center_y
    return math.hypot(start_x - center_x, start_y - center_y), center_x, center_y, wheel_radius


def _double_click_wheel(mouse_click_fn, x, y):
    if not mouse_click_fn(x, y):
        return False
    time.sleep(0.055)
    return mouse_click_fn(x, y, allow_rapid_repeat=True)


def reset_current_wheel_to_center_action(
    state_callbacks,
    detect_wheel_circle_in_area_fn,
    detect_handle_fn,
    mouse_click_fn,
    mouse_drag_begin_fn,
    mouse_drag_move_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    is_davinci_ready_for_interaction_fn,
    clear_hover_state_fn,
    davinci_running_fn,
    set_cursor_position_fn=None,
):
    if not is_davinci_ready_for_interaction_fn():
        clear_hover_state_fn(clear_areas=not davinci_running_fn())
        return False

    area = None
    current_hover_area = state_callbacks['current_hover_area_fn']()
    if current_hover_area and current_hover_area.get('type') == 'wheel':
        area = current_hover_area
    else:
        wheel_drag = state_callbacks['wheel_drag_state_fn']()
        if wheel_drag:
            area = wheel_drag.get('area')

    if not area or area.get('type') != 'wheel':
        return False

    release_param_drag_fn()
    release_wheel_drag_fn()

    area_name = area['name']
    handle = None
    center_x, center_y, wheel_radius = _wheel_center_from_handle_or_area(
        area,
        None,
        detect_wheel_circle_in_area_fn,
    )
    click_x, click_y, click_source = center_x, center_y, 'wheel_center'
    original_x, original_y = get_cursor_position_fn()

    if not _double_click_wheel(mouse_click_fn, click_x, click_y):
        return False

    if set_cursor_position_fn:
        set_cursor_position_fn(int(round(original_x)), int(round(original_y)))

    time.sleep(0.14)
    verified_handle = detect_handle_fn(area_name)
    if verified_handle:
        distance, center_x, center_y, wheel_radius = _handle_distance_from_center(
            area,
            verified_handle,
            detect_wheel_circle_in_area_fn,
        )
        threshold = max(3.0, min(6.0, wheel_radius * 0.12))
        if distance > threshold:
            print(
                f"reset {area_name} double-click unverified: "
                f"source={click_source} click=({click_x:.0f},{click_y:.0f}) "
                f"distance={distance:.1f} threshold={threshold:.1f}"
            )
            return False
        handle = verified_handle
    else:
        distance = 0.0
        threshold = max(3.0, min(6.0, wheel_radius * 0.12))

    state_callbacks['commit_wheel_center_reset_state_fn'](
        area,
        handle,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        angle=-math.pi / 2,
        updated_at=time.time(),
    )
    print(
        f"reset {area_name} by wheel double-click: "
        f"source={click_source} click=({click_x:.0f},{click_y:.0f}) "
        f"distance={distance:.1f} threshold={threshold:.1f}"
    )
    return True


__all__ = [
    'reset_current_wheel_to_center_action',
    'reset_wheel_via_native_button',
    'wheel_reset_button_point',
]
