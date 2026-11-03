"""Geometry preparation helpers for diameter push/pull wheel gestures."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_STATE_RADIUS,
    WHEEL_HANDLE_CENTER_IGNORE_RADIUS,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_diameter_geometry import (
    wheel_diameter_max_radius,
    wheel_diameter_project_handle_to_axis,
)
from .wheel_state_helpers import (
    clamp_max_radius_with_effective,
    resolve_effective_max_radius,
    resolve_outer_control_radius,
)
from .wheel_visual_radius import (
    resolve_wheel_outer_control_radius,
    wheel_visual_radius,
)


def wheel_diameter_geometry_context(area, handle, state=None, reuse_state=False, previous=None, wheel_state=None):
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    wheel_radius = handle.get('wheel_radius')
    max_radius = wheel_diameter_max_radius(area, center_x, center_y, wheel_radius)
    state_source = state if reuse_state else None
    effective_max_radius = resolve_effective_max_radius(
        state_source,
        handle,
        previous,
        wheel_state,
    )
    max_radius = clamp_max_radius_with_effective(max_radius, effective_max_radius)
    visual_radius = wheel_visual_radius(area, wheel_radius)
    cached_outer_control_radius = resolve_outer_control_radius(
        state_source,
        previous,
        wheel_state,
    )
    outer_control_radius = resolve_wheel_outer_control_radius(
        area,
        center_x,
        center_y,
        visual_radius=visual_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=cached_outer_control_radius,
    )
    return {
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'visual_radius': visual_radius,
        'outer_control_radius': outer_control_radius,
    }


def wheel_diameter_replaced_geometry_context(
    area,
    handle,
    effective_max_radius,
    cached_outer_control_radius,
):
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    wheel_radius = handle.get('wheel_radius')
    max_radius = wheel_diameter_max_radius(area, center_x, center_y, wheel_radius)
    max_radius = clamp_max_radius_with_effective(max_radius, effective_max_radius)
    visual_radius = wheel_visual_radius(area, wheel_radius)
    outer_control_radius = resolve_wheel_outer_control_radius(
        area,
        center_x,
        center_y,
        visual_radius=visual_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=cached_outer_control_radius,
    )
    return {
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'max_radius': max_radius,
        'visual_radius': visual_radius,
        'outer_control_radius': outer_control_radius,
    }


def wheel_diameter_fresh_center_context(
    handle,
    area,
    state,
    center_x,
    center_y,
    reuse_state,
    state_needs_fresh_handle,
):
    result = {
        'handle': handle,
        'center_x': center_x,
        'center_y': center_y,
        'adjusted': False,
        'center_drift': None,
        'center_drift_limit': None,
    }
    if not (handle and state_needs_fresh_handle and reuse_state and state):
        return result

    try:
        state_center_x = float(state.get('center_x', center_x))
        state_center_y = float(state.get('center_y', center_y))
    except (TypeError, ValueError):
        state_center_x = center_x
        state_center_y = center_y
    center_drift = math.hypot(state_center_x - center_x, state_center_y - center_y)
    center_drift_limit = max(12.0, min(area.get('w', 0), area.get('h', 0)) * 0.25)
    result.update({
        'center_drift': center_drift,
        'center_drift_limit': center_drift_limit,
    })
    if center_drift > center_drift_limit:
        return result

    adjusted_handle = dict(handle)
    adjusted_handle['wheel_center_x'] = state_center_x
    adjusted_handle['wheel_center_y'] = state_center_y
    if state.get('wheel_radius'):
        adjusted_handle['wheel_radius'] = state.get('wheel_radius')
    result.update({
        'handle': adjusted_handle,
        'center_x': state_center_x,
        'center_y': state_center_y,
        'adjusted': True,
    })
    return result


def wheel_diameter_center_detection_fallback(
    handle,
    previous,
    previous_has_handle,
    reuse_state,
    used_cached_handle,
    state_needs_fresh_handle,
    state,
    center_x,
    center_y,
):
    result = {
        'handle': handle,
        'center_x': center_x,
        'center_y': center_y,
        'used_cached_handle': used_cached_handle,
        'replaced': False,
        'detected_distance': None,
        'previous_distance': None,
    }
    if not (
        handle
        and reuse_state
        and previous_has_handle
        and not used_cached_handle
        and not state_needs_fresh_handle
        and previous
    ):
        return result

    detected_distance = math.hypot(handle['x'] - center_x, handle['y'] - center_y)
    state_signed_radius = state.get('signed_radius') if state else None
    previous_distance = (
        abs(state_signed_radius)
        if state_signed_radius is not None
        else math.hypot(previous['x'] - center_x, previous['y'] - center_y)
    )
    result.update({
        'detected_distance': detected_distance,
        'previous_distance': previous_distance,
    })
    if not (
        detected_distance < WHEEL_HANDLE_CENTER_IGNORE_RADIUS
        and previous_distance >= WHEEL_ROTATION_MIN_RADIUS
    ):
        return result

    fallback_handle = dict(previous)
    result.update({
        'handle': fallback_handle,
        'center_x': fallback_handle.get('wheel_center_x', center_x),
        'center_y': fallback_handle.get('wheel_center_y', center_y),
        'used_cached_handle': True,
        'replaced': True,
    })
    return result


def wheel_diameter_center_state_fallback(
    handle,
    previous,
    previous_has_handle,
    reuse_state,
    state_needs_fresh_handle,
    state,
    center_x,
    center_y,
    used_cached_handle,
):
    result = {
        'handle': handle,
        'center_x': center_x,
        'center_y': center_y,
        'used_cached_handle': used_cached_handle,
        'replaced': False,
        'state_signed_radius': None,
    }
    if not (
        handle
        and reuse_state
        and not state_needs_fresh_handle
        and state
        and previous_has_handle
        and previous
    ):
        return result

    state_signed_radius = state.get('signed_radius')
    result['state_signed_radius'] = state_signed_radius
    if state_signed_radius is None or abs(state_signed_radius) > WHEEL_DIAMETER_CENTER_STATE_RADIUS:
        return result

    fallback_handle = dict(previous)
    result.update({
        'handle': fallback_handle,
        'center_x': fallback_handle.get('wheel_center_x', center_x),
        'center_y': fallback_handle.get('wheel_center_y', center_y),
        'used_cached_handle': True,
        'replaced': True,
    })
    return result


def wheel_diameter_fresh_projection_context(
    handle,
    center_x,
    center_y,
    max_radius,
    reuse_state,
    state_needs_fresh_handle,
    state,
):
    result = {
        'handle': handle,
        'projected': False,
        'projected_signed_radius': None,
        'projected_cross': None,
        'raw_x': handle.get('x', 0) if handle else 0,
        'raw_y': handle.get('y', 0) if handle else 0,
    }
    if not (
        handle
        and state_needs_fresh_handle
        and reuse_state
        and state
        and state.get('axis_angle') is not None
    ):
        return result

    try:
        projected_handle, projected_signed_radius, projected_cross = (
            wheel_diameter_project_handle_to_axis(
                handle,
                center_x,
                center_y,
                float(state.get('axis_angle')),
                max_radius,
            )
        )
    except (TypeError, ValueError, KeyError):
        return result

    if not projected_handle:
        return result

    result.update({
        'handle': projected_handle,
        'projected': True,
        'projected_signed_radius': projected_signed_radius,
        'projected_cross': projected_cross,
    })
    return result


__all__ = [
    'wheel_diameter_center_detection_fallback',
    'wheel_diameter_center_state_fallback',
    'wheel_diameter_fresh_center_context',
    'wheel_diameter_fresh_projection_context',
    'wheel_diameter_geometry_context',
    'wheel_diameter_replaced_geometry_context',
]
