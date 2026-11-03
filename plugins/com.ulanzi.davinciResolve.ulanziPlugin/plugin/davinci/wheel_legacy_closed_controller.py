"""Legacy closed-loop wheel rotation fallback."""

import math
import time

from .config import (
    WHEEL_DRAG_DURATION_SECONDS,
    WHEEL_EDGE_PADDING,
    WHEEL_HANDLE_EDGE_PADDING,
    WHEEL_MOUSE_DELTA_GAIN,
    WHEEL_MOUSE_DELTA_STEPS,
    WHEEL_ROTATE_DEGREES_PER_TICK,
    WHEEL_ROTATION_INPUT_ANGLE_SCALE,
    WHEEL_ROTATION_MIN_RADIUS,
    WHEEL_ROTATION_POSITION_CORRECTION_GAIN,
    WHEEL_ROTATION_RADIAL_CORRECTION,
    WHEEL_ROTATION_SAFE_RADIUS_RATIO,
)
from .wheel_orbit_geometry import build_wheel_polar_delta


def handle_wheel_dial_rotate_closed(
    area,
    ticks,
    detect_wheel_circle_in_area_fn,
    detect_handle_fn,
    mouse_drag_begin_fn,
    mouse_drag_move_by_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    release_wheel_drag_fn,
    state_callbacks,
    sensitivity,
    set_cursor_position_fn=None,
):
    if ticks == 0:
        return False

    release_wheel_drag_fn()
    area_name = area['name']
    handle = detect_handle_fn(area_name)
    if 'wheel_center_x' not in handle or 'wheel_center_y' not in handle or 'wheel_radius' not in handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        if wheel_geometry:
            handle.update(wheel_geometry)

    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    wheel_radius = handle.get('wheel_radius')
    if wheel_radius:
        safe_radius = max(
            WHEEL_ROTATION_MIN_RADIUS,
            min(
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius - WHEEL_HANDLE_EDGE_PADDING),
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius * WHEEL_ROTATION_SAFE_RADIUS_RATIO),
            ),
        )
    else:
        safe_radius = max(WHEEL_ROTATION_MIN_RADIUS, min(area['w'], area['h']) / 2 - WHEEL_EDGE_PADDING)

    dx = handle['x'] - center_x
    dy = handle['y'] - center_y
    radius = math.hypot(dx, dy)
    angle = math.atan2(dy, dx) if radius >= 2 else handle.get('angle', 0.0)
    active_radius = min(max(WHEEL_ROTATION_MIN_RADIUS, radius), safe_radius)
    delta_angle = math.radians(
        ticks
        * sensitivity
        * WHEEL_ROTATE_DEGREES_PER_TICK
        * WHEEL_ROTATION_INPUT_ANGLE_SCALE
    )

    start_x = center_x + math.cos(angle) * active_radius
    start_y = center_y + math.sin(angle) * active_radius
    step_dx, step_dy = build_wheel_polar_delta(
        active_radius,
        angle,
        delta_angle,
        WHEEL_ROTATION_RADIAL_CORRECTION,
    )
    correction_dx = (start_x - handle['x']) * WHEEL_ROTATION_POSITION_CORRECTION_GAIN
    correction_dy = (start_y - handle['y']) * WHEEL_ROTATION_POSITION_CORRECTION_GAIN
    total_dx = step_dx * WHEEL_MOUSE_DELTA_GAIN + correction_dx
    total_dy = step_dy * WHEEL_MOUSE_DELTA_GAIN + correction_dy

    if not mouse_drag_begin_fn(handle['x'], handle['y']):
        return False

    moved = False
    cursor_end_x, cursor_end_y = handle['x'], handle['y']
    try:
        print(
            f"\u9420\u5b2a\u556f\u93c6?{area_name}: closed angle={math.degrees(angle + delta_angle):.1f} "
            f"radius={active_radius:.0f} input=({total_dx:.0f}, {total_dy:.0f})"
        )
        moved = mouse_drag_move_by_path_fn(
            total_dx,
            total_dy,
            steps=WHEEL_MOUSE_DELTA_STEPS,
            duration=WHEEL_DRAG_DURATION_SECONDS,
        )
        cursor_end_x, cursor_end_y = get_cursor_position_fn()
    finally:
        mouse_drag_end_fn(cursor_end_x, cursor_end_y)

    predicted_handle_x = center_x + math.cos(angle + delta_angle) * active_radius
    predicted_handle_y = center_y + math.sin(angle + delta_angle) * active_radius
    if set_cursor_position_fn:
        set_cursor_position_fn(int(round(predicted_handle_x)), int(round(predicted_handle_y)))

    state_callbacks['commit_wheel_predicted_handle_fn'](
        area,
        area_name,
        center_x,
        center_y,
        wheel_radius,
        predicted_handle_x,
        predicted_handle_y,
        angle + delta_angle,
        active_radius,
        updated_at=time.time(),
    )
    return moved


__all__ = ['handle_wheel_dial_rotate_closed']
