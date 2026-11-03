"""Retry path planning for diameter push/pull gestures."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS,
    WHEEL_DIAMETER_CENTER_CROSS_EPSILON,
    WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS,
    WHEEL_DIAMETER_CENTER_MOUSE_INPUT_GAIN,
    WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_PX,
    WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_RATIO,
    WHEEL_DIAMETER_DRAG_DURATION_SECONDS,
    WHEEL_DIAMETER_MOUSE_DELTA_STEPS,
    WHEEL_DIAMETER_MOUSE_INPUT_GAIN,
    WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX,
    WHEEL_DIAMETER_OUTER_BRIDGE_DURATION_SECONDS,
    WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED,
    WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS,
    WHEEL_DIAMETER_OUTER_CONTROL_ENABLED,
    WHEEL_DIAMETER_SAFE_PRESS_ORIGIN_EDGE_RATIO,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_common_geometry import build_linear_path
from .wheel_diameter_geometry import (
    build_wheel_diameter_center_cross_path,
    build_wheel_diameter_outer_bridge_path,
    build_wheel_diameter_outer_jump_path,
    wheel_diameter_safe_press_point,
)


def wheel_diameter_retry_plan(
    retry_handle,
    center_x,
    center_y,
    axis_angle,
    target_signed_radius,
    target_x,
    target_y,
    max_radius,
):
    retry_start_x = retry_handle['x']
    retry_start_y = retry_handle['y']
    retry_logical_start_x = retry_start_x
    retry_logical_start_y = retry_start_y
    retry_press_x = retry_start_x
    retry_press_y = retry_start_y
    retry_current_signed_radius = (
        (retry_start_x - center_x) * math.cos(axis_angle)
        + (retry_start_y - center_y) * math.sin(axis_angle)
    )
    retry_initial_signed_radius = retry_current_signed_radius
    retry_outer_jump = bool(
        WHEEL_DIAMETER_OUTER_CONTROL_ENABLED
        and target_signed_radius * retry_current_signed_radius < 0
    )
    retry_safe_signed_radius = None
    if retry_outer_jump:
        retry_press_x = target_x
        retry_press_y = target_y
        retry_logical_start_x = target_x
        retry_logical_start_y = target_y
        retry_current_signed_radius = target_signed_radius
    else:
        retry_safe_origin_edge_radius = max(
            WHEEL_ROTATION_MIN_RADIUS,
            max_radius * WHEEL_DIAMETER_SAFE_PRESS_ORIGIN_EDGE_RATIO,
        )
        retry_safe_press_allowed = (
            abs(retry_current_signed_radius) >= retry_safe_origin_edge_radius
            and retry_current_signed_radius * (
                target_signed_radius - retry_current_signed_radius
            ) < 0
        )
        if retry_safe_press_allowed:
            retry_press_x, retry_press_y = wheel_diameter_safe_press_point(
                center_x,
                center_y,
                axis_angle,
                retry_current_signed_radius,
                retry_start_x,
                retry_start_y,
                max_radius,
            )
        retry_safe_signed_radius = (
            (retry_press_x - center_x) * math.cos(axis_angle)
            + (retry_press_y - center_y) * math.sin(axis_angle)
        )

    retry_safe_press_used = math.hypot(
        retry_press_x - retry_logical_start_x,
        retry_press_y - retry_logical_start_y,
    ) > 0.5
    retry_safe_origin_inward = (
        retry_safe_press_used
        and not retry_outer_jump
        and retry_current_signed_radius * (
            target_signed_radius - retry_current_signed_radius
        ) < 0
    )
    if retry_safe_origin_inward:
        retry_current_signed_radius = max(
            -max_radius,
            min(max_radius, retry_safe_signed_radius),
        )
        retry_logical_start_x = retry_press_x
        retry_logical_start_y = retry_press_y

    retry_crossing = (
        not retry_outer_jump
        and abs(retry_current_signed_radius) > WHEEL_DIAMETER_CENTER_CROSS_EPSILON
        and abs(target_signed_radius) > WHEEL_DIAMETER_CENTER_CROSS_EPSILON
        and retry_current_signed_radius * target_signed_radius < 0
    )
    retry_outer_bridge = bool(
        WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED
        and retry_crossing
    )
    retry_center_direct_crossing = bool(retry_crossing)
    if retry_center_direct_crossing:
        retry_outer_bridge = False
    retry_center_crossing = retry_crossing and not retry_outer_bridge and not retry_center_direct_crossing
    retry_dx = target_x - retry_logical_start_x
    retry_dy = target_y - retry_logical_start_y
    retry_mouse_target_x = target_x
    retry_mouse_target_y = target_y
    input_gain = max(1.0, WHEEL_DIAMETER_MOUSE_INPUT_GAIN)
    center_input_gain = max(input_gain, WHEEL_DIAMETER_CENTER_MOUSE_INPUT_GAIN)
    if retry_center_direct_crossing and center_input_gain > 1.0:
        retry_mouse_target_x = retry_press_x + retry_dx * center_input_gain
        retry_mouse_target_y = retry_press_y + retry_dy * center_input_gain
        retry_mouse_distance = math.hypot(
            retry_mouse_target_x - retry_press_x,
            retry_mouse_target_y - retry_press_y,
        )
        retry_max_center_mouse_distance = max(
            math.hypot(retry_dx, retry_dy),
            min(
                WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_PX,
                max_radius * WHEEL_DIAMETER_CENTER_MOUSE_MAX_DISTANCE_RATIO,
            ),
        )
        if retry_mouse_distance > retry_max_center_mouse_distance > 0:
            retry_scale = retry_max_center_mouse_distance / retry_mouse_distance
            retry_mouse_target_x = retry_press_x + (retry_mouse_target_x - retry_press_x) * retry_scale
            retry_mouse_target_y = retry_press_y + (retry_mouse_target_y - retry_press_y) * retry_scale
    elif not retry_crossing and not retry_outer_jump and input_gain > 1.0:
        retry_mouse_target_x = retry_press_x + retry_dx * input_gain
        retry_mouse_target_y = retry_press_y + retry_dy * input_gain

    retry_mouse_dx = retry_mouse_target_x - retry_press_x
    retry_mouse_dy = retry_mouse_target_y - retry_press_y
    retry_path_dx = (
        retry_mouse_dx
        if (not retry_crossing or retry_center_direct_crossing) and not retry_outer_jump
        else retry_dx
    )
    retry_path_dy = (
        retry_mouse_dy
        if (not retry_crossing or retry_center_direct_crossing) and not retry_outer_jump
        else retry_dy
    )
    retry_steps = WHEEL_DIAMETER_MOUSE_DELTA_STEPS
    if WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX > 0:
        retry_steps = max(
            retry_steps,
            int(math.ceil(math.hypot(retry_path_dx, retry_path_dy) / WHEEL_DIAMETER_MOUSE_RELATIVE_MAX_STEP_PX)),
        )
    retry_duration = WHEEL_DIAMETER_DRAG_DURATION_SECONDS
    retry_mode = 'center-direct' if retry_center_direct_crossing else ('outer-jump' if retry_outer_jump else 'direct')
    if retry_center_direct_crossing:
        retry_steps = max(retry_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        retry_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        retry_path = build_linear_path(
            retry_press_x,
            retry_press_y,
            retry_mouse_target_x,
            retry_mouse_target_y,
            steps=retry_steps,
        )
    elif retry_outer_jump:
        retry_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        retry_path = build_wheel_diameter_outer_jump_path(
            center_x,
            center_y,
            axis_angle,
            target_signed_radius,
            max_radius,
        )
    elif retry_outer_bridge:
        retry_mode = 'outer-bridge'
        retry_steps = max(retry_steps, WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS)
        retry_duration = WHEEL_DIAMETER_OUTER_BRIDGE_DURATION_SECONDS
        retry_path = build_wheel_diameter_outer_bridge_path(
            center_x,
            center_y,
            axis_angle,
            retry_press_x,
            retry_press_y,
            retry_current_signed_radius,
            target_x,
            target_y,
            target_signed_radius,
            max_radius,
            retry_steps,
        )
    elif retry_center_crossing:
        retry_mode = 'center-bypass'
        retry_steps = max(retry_steps, WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS)
        retry_duration = WHEEL_DIAMETER_CENTER_CROSS_DURATION_SECONDS
        retry_path = build_wheel_diameter_center_cross_path(
            center_x,
            center_y,
            axis_angle,
            retry_press_x,
            retry_press_y,
            retry_current_signed_radius,
            target_x,
            target_y,
            target_signed_radius,
            max_radius,
            retry_steps,
        )
    else:
        retry_path = build_linear_path(
            retry_press_x,
            retry_press_y,
            retry_mouse_target_x,
            retry_mouse_target_y,
            steps=retry_steps,
        )

    return {
        'retry_start_x': retry_start_x,
        'retry_start_y': retry_start_y,
        'retry_logical_start_x': retry_logical_start_x,
        'retry_logical_start_y': retry_logical_start_y,
        'retry_press_x': retry_press_x,
        'retry_press_y': retry_press_y,
        'retry_initial_signed_radius': retry_initial_signed_radius,
        'retry_current_signed_radius': retry_current_signed_radius,
        'retry_outer_jump': retry_outer_jump,
        'retry_safe_signed_radius': retry_safe_signed_radius,
        'retry_safe_press_used': retry_safe_press_used,
        'retry_safe_origin_inward': retry_safe_origin_inward,
        'retry_crossing': retry_crossing,
        'retry_outer_bridge': retry_outer_bridge,
        'retry_center_direct_crossing': retry_center_direct_crossing,
        'retry_center_crossing': retry_center_crossing,
        'retry_dx': retry_dx,
        'retry_dy': retry_dy,
        'retry_mouse_target_x': retry_mouse_target_x,
        'retry_mouse_target_y': retry_mouse_target_y,
        'retry_mouse_dx': retry_mouse_dx,
        'retry_mouse_dy': retry_mouse_dy,
        'retry_steps': retry_steps,
        'retry_duration': retry_duration,
        'retry_mode': retry_mode,
        'retry_path': retry_path,
    }


__all__ = ['wheel_diameter_retry_plan']
