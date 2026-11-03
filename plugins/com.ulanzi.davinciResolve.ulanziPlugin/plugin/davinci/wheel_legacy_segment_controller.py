"""Legacy segment wheel rotation fallback."""

import math
import time

from .area_target_helpers import area_key
from .config import (
    WHEEL_CENTER_FALLBACK_RADIUS,
    WHEEL_DRAG_DURATION_SECONDS,
    WHEEL_EDGE_PADDING,
    WHEEL_HANDLE_CACHE_SECONDS,
    WHEEL_HANDLE_OUTER_TOLERANCE,
    WHEEL_MOUSE_DELTA_GAIN,
    WHEEL_MOUSE_DELTA_STEPS,
    WHEEL_MOUSE_RELATIVE_MAX_STEP_PX,
    WHEEL_ORBIT_CENTER_DEADZONE_RADIUS,
    WHEEL_ROTATE_DEGREES_PER_TICK,
    WHEEL_ROTATION_MIN_RADIUS,
    WHEEL_ROTATION_RADIAL_CORRECTION,
    WHEEL_SEGMENT_RADIUS_CORRECTION_GAIN,
    WHEEL_SEGMENT_RADIUS_CORRECTION_MAX_PX,
    WHEEL_SEGMENT_RADIUS_RESET_THRESHOLD,
    WHEEL_SEGMENT_REDETECT_HANDLE,
    WHEEL_SEGMENT_SESSION_SECONDS,
)
from .wheel_diameter_geometry import wheel_diameter_mouse_start_point
from .wheel_fallback_handle import make_center_fallback_handle
from .wheel_orbit_geometry import build_wheel_polar_delta


def handle_wheel_dial_rotate_segment(
    area,
    ticks,
    detect_wheel_circle_in_area_fn,
    detect_handle_fn,
    mouse_drag_begin_fn,
    mouse_drag_move_by_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    detect_handle_raw_for_area_fn,
    clear_wheel_orbit_fn,
    release_param_drag_fn,
    release_wheel_drag_fn,
    diameter_rotate_fn,
    state_callbacks,
    sensitivity,
    set_cursor_position_fn=None,
    debug_slow_fn=None,
):
    if ticks == 0:
        return False

    clear_wheel_orbit_fn()
    state_callbacks['clear_wheel_diameter_state_fn']()
    release_param_drag_fn()
    release_wheel_drag_fn()

    area_name = area['name']
    target_key = area_key(area)
    now = time.time()
    handle = detect_handle_raw_for_area_fn(area) if WHEEL_SEGMENT_REDETECT_HANDLE else None
    previous = state_callbacks['wheel_handle_for_area_fn'](area_name)
    if (
        not handle
        and
        previous
        and now - previous.get('updated_at', 0) <= WHEEL_HANDLE_CACHE_SECONDS
        and all(key in previous for key in ('x', 'y', 'wheel_center_x', 'wheel_center_y'))
    ):
        handle = dict(previous)

    if not handle:
        handle = detect_handle_fn(area_name)
    if not handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        handle = make_center_fallback_handle(
            area,
            wheel_geometry,
            source='segment_center_fallback',
        )
    if handle and handle.get('center_fallback'):
        state_callbacks['commit_wheel_raw_handle_fn'](area, handle, area_name=area_name)
        if debug_slow_fn:
            debug_slow_fn(f"segment center fallback -> diameter {area_name}")
        return diameter_rotate_fn(area, ticks)
    if not handle:
        print(f"\u95ba\u582b\u4e9d\u6fb9\u6a40\u5d1a?{area_name} \u95bb\u3125\u5aef\u9428\u71bc\u61de\u934c\u6ec3\u4eef")
        return False

    if 'wheel_center_x' not in handle or 'wheel_center_y' not in handle or 'wheel_radius' not in handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        if wheel_geometry:
            handle.update(wheel_geometry)

    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    wheel_radius = handle.get('wheel_radius')
    if wheel_radius:
        max_radius = max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius + WHEEL_HANDLE_OUTER_TOLERANCE)
    else:
        max_radius = max(WHEEL_ROTATION_MIN_RADIUS, min(area['w'], area['h']) / 2 - WHEEL_EDGE_PADDING)

    dx = handle['x'] - center_x
    dy = handle['y'] - center_y
    actual_radius = math.hypot(dx, dy)
    center_deadzone = max(WHEEL_ORBIT_CENTER_DEADZONE_RADIUS, WHEEL_CENTER_FALLBACK_RADIUS)
    if actual_radius <= center_deadzone:
        center_geometry = (
            {
                'wheel_center_x': center_x,
                'wheel_center_y': center_y,
                'wheel_radius': wheel_radius,
            }
            if wheel_radius
            else None
        )
        center_handle = make_center_fallback_handle(
            area,
            center_geometry,
            source='segment_center_deadzone',
        )
        if center_handle:
            state_callbacks['commit_wheel_raw_handle_fn'](area, center_handle, area_name=area_name)
        if debug_slow_fn:
            debug_slow_fn(
                f"segment center deadzone -> diameter {area_name} "
                f"radius={actual_radius:.1f}"
            )
        return diameter_rotate_fn(area, ticks)
    angle = math.atan2(dy, dx) if actual_radius >= 2 else handle.get('angle', 0.0)
    segment_state = state_callbacks['wheel_segment_state_fn']()
    reuse_segment_state = (
        segment_state
        and segment_state.get('target_key') == target_key
        and now - segment_state.get('updated_at', 0) <= WHEEL_SEGMENT_SESSION_SECONDS
    )
    if reuse_segment_state:
        locked_radius = min(
            max(WHEEL_ROTATION_MIN_RADIUS, segment_state.get('radius', actual_radius)),
            max_radius,
        )
        if abs(actual_radius - locked_radius) > WHEEL_SEGMENT_RADIUS_RESET_THRESHOLD:
            radius = min(max(WHEEL_ROTATION_MIN_RADIUS, actual_radius), max_radius)
            reuse_segment_state = False
        else:
            radius = locked_radius
    else:
        radius = min(max(WHEEL_ROTATION_MIN_RADIUS, actual_radius), max_radius)

    delta_angle = math.radians(ticks * sensitivity * WHEEL_ROTATE_DEGREES_PER_TICK)
    target_angle = angle + delta_angle
    step_dx, step_dy = build_wheel_polar_delta(
        radius,
        angle,
        delta_angle,
        WHEEL_ROTATION_RADIAL_CORRECTION,
    )
    radius_error = radius - actual_radius
    radial_move = radius_error * WHEEL_SEGMENT_RADIUS_CORRECTION_GAIN
    if abs(radial_move) > WHEEL_SEGMENT_RADIUS_CORRECTION_MAX_PX:
        radial_move = math.copysign(WHEEL_SEGMENT_RADIUS_CORRECTION_MAX_PX, radial_move)
    radial_dx = math.cos(angle) * radial_move
    radial_dy = math.sin(angle) * radial_move
    total_dx = step_dx * WHEEL_MOUSE_DELTA_GAIN + radial_dx
    total_dy = step_dy * WHEEL_MOUSE_DELTA_GAIN + radial_dy

    press_x, press_y = wheel_diameter_mouse_start_point(
        center_x,
        center_y,
        angle,
        radius,
        handle['x'],
        handle['y'],
        max_radius,
    )
    if not mouse_drag_begin_fn(press_x, press_y):
        return False

    moved = False
    cursor_end_x, cursor_end_y = press_x, press_y
    try:
        print(
            f"adjust {area_name}: segment angle={math.degrees(target_angle):.1f} "
            f"radius={radius:.0f} actual_radius={actual_radius:.0f} "
            f"radius_error={radius_error:.1f} radial=({radial_dx:.0f}, {radial_dy:.0f}) "
            f"input=({total_dx:.0f}, {total_dy:.0f}) "
            f"from=({handle['x']:.0f}, {handle['y']:.0f}) "
            f"press=({press_x:.0f}, {press_y:.0f})"
        )
        moved = mouse_drag_move_by_path_fn(
            total_dx,
            total_dy,
            steps=WHEEL_MOUSE_DELTA_STEPS,
            duration=WHEEL_DRAG_DURATION_SECONDS,
            max_step_px=WHEEL_MOUSE_RELATIVE_MAX_STEP_PX,
        )
        cursor_end_x, cursor_end_y = get_cursor_position_fn()
    finally:
        mouse_drag_end_fn(cursor_end_x, cursor_end_y)

    predicted_handle_x = center_x + math.cos(target_angle) * radius
    predicted_handle_y = center_y + math.sin(target_angle) * radius
    if set_cursor_position_fn:
        set_cursor_position_fn(int(round(predicted_handle_x)), int(round(predicted_handle_y)))

    updated_at = time.time()
    state_callbacks['commit_wheel_predicted_handle_fn'](
        area,
        area_name,
        center_x,
        center_y,
        wheel_radius,
        predicted_handle_x,
        predicted_handle_y,
        target_angle,
        radius,
        updated_at=updated_at,
        mark_recent=True,
    )
    state_callbacks['commit_wheel_segment_state_fn'](
        target_key,
        radius,
        updated_at=updated_at,
    )
    return moved


__all__ = ['handle_wheel_dial_rotate_segment']
