"""Mouse path planning for diameter push/pull gestures."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS,
    WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS,
    WHEEL_DIAMETER_CENTER_BYPASS_ENABLED,
    WHEEL_DIAMETER_CENTER_MOUSE_INPUT_GAIN,
    WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_PX,
    WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_RATIO,
    WHEEL_DIAMETER_CENTER_REPRESS_ENABLED,
    WHEEL_DIAMETER_CENTER_REPRESS_INSET_PX,
    WHEEL_DIAMETER_CENTER_REPRESS_MIN_RADIUS,
    WHEEL_DIAMETER_DRAG_DURATION_SECONDS,
    WHEEL_DIAMETER_MOUSE_DELTA_STEPS,
    WHEEL_DIAMETER_MOUSE_INPUT_GAIN,
    WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX,
    WHEEL_DIAMETER_OUTER_BRIDGE_DURATION_SECONDS,
    WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED,
    WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS,
    WHEEL_DIAMETER_OUTER_CONTROL_ENABLED,
)
from .wheel_common_geometry import build_linear_path
from .wheel_diameter_geometry import (
    build_wheel_diameter_center_cross_path,
    build_wheel_diameter_outer_bridge_path,
    build_wheel_diameter_outer_jump_path,
    wheel_diameter_point,
)


def wheel_diameter_mouse_plan(
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    target_signed_radius,
    target_x,
    target_y,
    max_radius,
    center_crossing,
    cursor_start_x,
    cursor_start_y,
    logical_start_x,
    logical_start_y,
):
    input_dx = target_x - logical_start_x
    input_dy = target_y - logical_start_y
    drag_duration = WHEEL_DIAMETER_DRAG_DURATION_SECONDS
    center_repress_crossing = bool(WHEEL_DIAMETER_CENTER_REPRESS_ENABLED and center_crossing)
    center_bypass_crossing = bool(
        WHEEL_DIAMETER_CENTER_BYPASS_ENABLED
        and center_crossing
        and not center_repress_crossing
    )
    center_direct_crossing = bool(
        center_crossing
        and not center_repress_crossing
        and not center_bypass_crossing
    )
    outer_control_crossing = bool(
        WHEEL_DIAMETER_OUTER_CONTROL_ENABLED
        and center_crossing
        and not center_repress_crossing
        and not center_bypass_crossing
    )
    outer_bridge_crossing = bool(
        WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED
        and center_crossing
        and not outer_control_crossing
        and not center_bypass_crossing
        and not center_direct_crossing
    )
    path_start_x = cursor_start_x
    path_start_y = cursor_start_y
    center_repress_press_x = None
    center_repress_press_y = None
    center_bypass_press_x = None
    center_bypass_press_y = None
    mouse_target_x = target_x
    mouse_target_y = target_y
    input_gain = max(1.0, WHEEL_DIAMETER_MOUSE_INPUT_GAIN)
    center_input_gain = max(input_gain, WHEEL_DIAMETER_CENTER_MOUSE_INPUT_GAIN)
    if center_repress_crossing:
        target_sign = 1.0 if target_signed_radius >= 0 else -1.0
        press_radius = min(
            abs(target_signed_radius),
            max(
                WHEEL_DIAMETER_CENTER_REPRESS_MIN_RADIUS,
                abs(target_signed_radius) - WHEEL_DIAMETER_CENTER_REPRESS_INSET_PX,
            ),
        )
        center_repress_press_x, center_repress_press_y = wheel_diameter_point(
            center_x,
            center_y,
            axis_angle,
            target_sign * press_radius,
        )
        path_start_x = center_repress_press_x
        path_start_y = center_repress_press_y
    elif center_direct_crossing and center_input_gain > 1.0:
        mouse_target_x = cursor_start_x + input_dx * center_input_gain
        mouse_target_y = cursor_start_y + input_dy * center_input_gain
        mouse_distance = math.hypot(mouse_target_x - cursor_start_x, mouse_target_y - cursor_start_y)
        max_center_mouse_distance = max(
            math.hypot(input_dx, input_dy),
            min(
                WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_PX,
                max_radius * WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_RATIO,
            ),
        )
        if mouse_distance > max_center_mouse_distance > 0:
            scale = max_center_mouse_distance / mouse_distance
            mouse_target_x = cursor_start_x + (mouse_target_x - cursor_start_x) * scale
            mouse_target_y = cursor_start_y + (mouse_target_y - cursor_start_y) * scale
    elif not center_crossing and input_gain > 1.0:
        mouse_target_x = cursor_start_x + input_dx * input_gain
        mouse_target_y = cursor_start_y + input_dy * input_gain

    mouse_input_dx = mouse_target_x - path_start_x
    mouse_input_dy = mouse_target_y - path_start_y
    path_distance_dx = mouse_input_dx if (not center_crossing or center_direct_crossing or center_repress_crossing) else input_dx
    path_distance_dy = mouse_input_dy if (not center_crossing or center_direct_crossing or center_repress_crossing) else input_dy
    path_steps = WHEEL_DIAMETER_MOUSE_DELTA_STEPS
    if WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX > 0:
        path_steps = max(
            path_steps,
            int(math.ceil(math.hypot(path_distance_dx, path_distance_dy) / WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX)),
        )

    drag_mode = (
        'center-repress'
        if center_repress_crossing
        else (
            'center-bypass'
            if center_bypass_crossing
            else ('center-direct' if center_direct_crossing else ('outer-jump' if outer_control_crossing else 'diameter'))
        )
    )
    if center_repress_crossing:
        path_steps = max(path_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        drag_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        move_path = build_linear_path(
            path_start_x,
            path_start_y,
            mouse_target_x,
            mouse_target_y,
            steps=path_steps,
        )
    elif center_bypass_crossing:
        path_start_x, path_start_y = wheel_diameter_point(
            center_x,
            center_y,
            axis_angle,
            signed_radius,
        )
        center_bypass_press_x = path_start_x
        center_bypass_press_y = path_start_y
        mouse_input_dx = target_x - path_start_x
        mouse_input_dy = target_y - path_start_y
        path_steps = max(path_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        drag_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        move_path = build_wheel_diameter_center_cross_path(
            center_x,
            center_y,
            axis_angle,
            path_start_x,
            path_start_y,
            signed_radius,
            target_x,
            target_y,
            target_signed_radius,
            max_radius,
            path_steps,
        )
    elif center_direct_crossing:
        path_steps = max(path_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        drag_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        move_path = build_linear_path(
            cursor_start_x,
            cursor_start_y,
            mouse_target_x,
            mouse_target_y,
            steps=path_steps,
        )
    elif outer_control_crossing:
        drag_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        move_path = build_wheel_diameter_outer_jump_path(
            center_x,
            center_y,
            axis_angle,
            target_signed_radius,
            max_radius,
        )
    elif outer_bridge_crossing:
        drag_mode = 'outer-bridge'
        path_steps = max(path_steps, WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS)
        drag_duration = WHEEL_DIAMETER_OUTER_BRIDGE_DURATION_SECONDS
        move_path = build_wheel_diameter_outer_bridge_path(
            center_x,
            center_y,
            axis_angle,
            cursor_start_x,
            cursor_start_y,
            signed_radius,
            target_x,
            target_y,
            target_signed_radius,
            max_radius,
            path_steps,
        )
    elif center_crossing:
        drag_mode = 'center-bypass'
        path_steps = max(path_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        drag_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        move_path = build_wheel_diameter_center_cross_path(
            center_x,
            center_y,
            axis_angle,
            cursor_start_x,
            cursor_start_y,
            signed_radius,
            target_x,
            target_y,
            target_signed_radius,
            max_radius,
            path_steps,
        )
    else:
        move_path = build_linear_path(
            cursor_start_x,
            cursor_start_y,
            mouse_target_x,
            mouse_target_y,
            steps=path_steps,
        )

    return {
        'input_dx': input_dx,
        'input_dy': input_dy,
        'mouse_target_x': mouse_target_x,
        'mouse_target_y': mouse_target_y,
        'mouse_input_dx': mouse_input_dx,
        'mouse_input_dy': mouse_input_dy,
        'path_steps': path_steps,
        'drag_duration': drag_duration,
        'drag_mode': drag_mode,
        'move_path': move_path,
        'center_repress_crossing': center_repress_crossing,
        'center_bypass_crossing': center_bypass_crossing,
        'center_repress_press_x': center_repress_press_x,
        'center_repress_press_y': center_repress_press_y,
        'center_bypass_press_x': center_bypass_press_x,
        'center_bypass_press_y': center_bypass_press_y,
        'center_direct_crossing': center_direct_crossing,
        'outer_control_crossing': outer_control_crossing,
        'outer_bridge_crossing': outer_bridge_crossing,
    }


__all__ = ['wheel_diameter_mouse_plan']
