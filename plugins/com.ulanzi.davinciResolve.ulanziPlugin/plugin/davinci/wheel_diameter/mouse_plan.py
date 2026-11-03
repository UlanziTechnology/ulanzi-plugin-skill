"""Cursor anchoring and mouse planning for diameter gestures."""

import math

from ..config import (
    WHEEL_DIAMETER_CURSOR_REANCHOR_AXIS_TOLERANCE_PX,
    WHEEL_DIAMETER_CURSOR_REANCHOR_CENTER_RADIUS,
    WHEEL_DIAMETER_CURSOR_REANCHOR_DISTANCE_PX,
    WHEEL_DIAMETER_CURSOR_REANCHOR_DISTANCE_RATIO,
)
from ..wheel_diameter_mouse_logic import wheel_diameter_mouse_plan


def _as_float(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _axis_cross_distance(x, y, center_x, center_y, axis_angle):
    return abs(
        -((x - center_x) * math.sin(axis_angle))
        + ((y - center_y) * math.cos(axis_angle))
    )


def _cursor_anchor(
    drag,
    center_x,
    center_y,
    axis_angle,
    max_radius,
    center_crossing,
    start_reference_x,
    start_reference_y,
):
    raw_x = _as_float(
        drag.get('x', drag.get('press_x', start_reference_x)),
        start_reference_x,
    )
    raw_y = _as_float(
        drag.get('y', drag.get('press_y', start_reference_y)),
        start_reference_y,
    )
    anchor_x = _as_float(
        drag.get('predicted_handle_x', start_reference_x),
        start_reference_x,
    )
    anchor_y = _as_float(
        drag.get('predicted_handle_y', start_reference_y),
        start_reference_y,
    )
    raw_cross = _axis_cross_distance(raw_x, raw_y, center_x, center_y, axis_angle)
    anchor_cross = _axis_cross_distance(
        anchor_x,
        anchor_y,
        center_x,
        center_y,
        axis_angle,
    )
    axis_drift = abs(raw_cross - anchor_cross)
    distance = math.hypot(raw_x - anchor_x, raw_y - anchor_y)
    anchor_radius = math.hypot(anchor_x - center_x, anchor_y - center_y)
    distance_tolerance = max(
        float(WHEEL_DIAMETER_CURSOR_REANCHOR_DISTANCE_PX),
        max_radius * float(WHEEL_DIAMETER_CURSOR_REANCHOR_DISTANCE_RATIO),
    )
    reason = None
    if axis_drift > float(WHEEL_DIAMETER_CURSOR_REANCHOR_AXIS_TOLERANCE_PX):
        reason = 'off-axis'
    elif distance > distance_tolerance:
        reason = 'far'

    suppressed_reason = None
    if reason == 'far':
        if center_crossing:
            suppressed_reason = 'center-cross-far'
        elif anchor_radius <= float(WHEEL_DIAMETER_CURSOR_REANCHOR_CENTER_RADIUS):
            suppressed_reason = 'near-center-anchor'

    use_anchor = bool(reason and not suppressed_reason)
    return {
        'cursor_start_x': anchor_x if use_anchor else raw_x,
        'cursor_start_y': anchor_y if use_anchor else raw_y,
        'raw_cursor_start_x': raw_x,
        'raw_cursor_start_y': raw_y,
        'cursor_anchor_x': anchor_x,
        'cursor_anchor_y': anchor_y,
        'cursor_anchor_radius': anchor_radius,
        'cursor_reanchor': use_anchor,
        'cursor_reanchor_reason': reason,
        'cursor_reanchor_suppressed': suppressed_reason,
        'cursor_axis_drift': axis_drift,
        'cursor_anchor_distance': distance,
    }


def build_diameter_mouse_plan(
    drag,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    target_signed_radius,
    target_x,
    target_y,
    max_radius,
    center_crossing,
    start_reference_x,
    start_reference_y,
):
    cursor_anchor = _cursor_anchor(
        drag,
        center_x,
        center_y,
        axis_angle,
        max_radius,
        center_crossing,
        start_reference_x,
        start_reference_y,
    )
    cursor_start_x = cursor_anchor['cursor_start_x']
    cursor_start_y = cursor_anchor['cursor_start_y']
    logical_start_x = drag.get('logical_start_x', start_reference_x)
    logical_start_y = drag.get('logical_start_y', start_reference_y)
    mouse_plan = wheel_diameter_mouse_plan(
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
    )
    mouse_plan.update(cursor_anchor)
    return {
        'mouse_plan': mouse_plan,
        'cursor_start_x': cursor_start_x,
        'cursor_start_y': cursor_start_y,
        'logical_start_x': logical_start_x,
        'logical_start_y': logical_start_y,
        'outer_control_crossing': mouse_plan['outer_control_crossing'],
    }


__all__ = ['build_diameter_mouse_plan']
