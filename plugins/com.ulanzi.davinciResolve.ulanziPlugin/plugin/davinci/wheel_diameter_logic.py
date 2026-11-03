"""Decision helpers for diameter push/pull wheel gestures."""

import math

from .config import (
    WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS,
    WHEEL_DIAMETER_AXIS_LOCK_NEAR_CENTER_RADIUS,
    WHEEL_DIAMETER_AXIS_LOCK_SECONDS,
    WHEEL_DIAMETER_EDGE_LOCK_EPSILON,
    WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED,
    WHEEL_DIAMETER_OUTER_CONTROL_ENABLED,
    WHEEL_DIAMETER_OUTER_CONTROL_WRONG_SIDE_LOCK_RADIUS,
    WHEEL_DIAMETER_SAFE_PRESS_ORIGIN_EDGE_RATIO,
    WHEEL_RADIAL_PIXELS_PER_TICK,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_common_geometry import normalize_angle_radians
from .wheel_diameter_geometry import (
    wheel_diameter_axis_from_small_vector,
    wheel_diameter_axis_from_vector,
    wheel_diameter_display_angle,
    wheel_diameter_outer_control_point,
    wheel_diameter_point,
    wheel_diameter_safe_press_point,
)


def wheel_diameter_axis_lock_for_area(lock, target_key, area, center_x=None, center_y=None, now=None):
    if not lock or not area:
        return None

    if lock.get('target_key') != target_key:
        return None

    now = now if now is not None else 0.0
    if now - lock.get('updated_at', 0) > WHEEL_DIAMETER_AXIS_LOCK_SECONDS:
        return None

    if center_x is not None and center_y is not None:
        try:
            drift = math.hypot(
                float(lock.get('center_x', center_x)) - float(center_x),
                float(lock.get('center_y', center_y)) - float(center_y),
            )
        except (TypeError, ValueError):
            return None
        if drift > max(12.0, min(area.get('w', 0), area.get('h', 0)) * 0.25):
            return None

    return lock


def _trusted_handle_axis_source(handle):
    source = str(handle.get('source') or '')
    if source.startswith(('diameter_anchor', 'hover_detect', 'manual_release')):
        return source or 'handle'
    return None


def wheel_diameter_axis_context(
    handle,
    center_x,
    center_y,
    actual_radius,
    max_radius,
    reuse_state,
    state,
    state_needs_fresh_handle,
    used_cached_handle,
    axis_lock,
):
    dx = handle['x'] - center_x
    dy = handle['y'] - center_y
    debug_kind = None
    projected_radius = None
    state_signed_radius = None

    if reuse_state:
        axis_angle = state['axis_angle']
        projected_radius = dx * math.cos(axis_angle) + dy * math.sin(axis_angle)
        state_signed_radius = state.get('signed_radius')
        projected_wrong_side = (
            not state_needs_fresh_handle
            and (WHEEL_DIAMETER_OUTER_CONTROL_ENABLED or WHEEL_DIAMETER_OUTER_BRIDGE_ENABLED)
            and state_signed_radius is not None
            and abs(state_signed_radius) >= WHEEL_DIAMETER_OUTER_CONTROL_WRONG_SIDE_LOCK_RADIUS
            and abs(projected_radius) >= WHEEL_DIAMETER_OUTER_CONTROL_WRONG_SIDE_LOCK_RADIUS
            and state_signed_radius * projected_radius < 0
        )
        if projected_wrong_side:
            debug_kind = 'outer_state_lock'
        use_state_radius = (
            not state_needs_fresh_handle
            and (
                used_cached_handle
                or projected_wrong_side
                or (
                    state_signed_radius is not None
                    and abs(state_signed_radius) >= max_radius - WHEEL_DIAMETER_EDGE_LOCK_EPSILON
                )
            )
        )
        signed_radius = state_signed_radius if use_state_radius else projected_radius
        axis_lock_source = 'state'
    else:
        handle_axis = handle.get('radial_axis_angle')
        try:
            handle_signed_radius = float(handle.get('signed_radius'))
        except (TypeError, ValueError):
            handle_signed_radius = None
        try:
            lock_signed_radius = float(axis_lock.get('signed_radius', 0.0)) if axis_lock else 0.0
        except (TypeError, ValueError):
            lock_signed_radius = 0.0

        locked_axis = None
        axis_lock_source = None
        trusted_handle_source = _trusted_handle_axis_source(handle)
        if (
            handle_axis is not None
            and trusted_handle_source
            and actual_radius >= WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS
        ):
            locked_axis = float(handle_axis)
            axis_lock_source = trusted_handle_source
        elif handle_axis is not None and actual_radius <= WHEEL_DIAMETER_AXIS_LOCK_NEAR_CENTER_RADIUS:
            locked_axis = float(handle_axis)
            axis_lock_source = 'handle'
        elif axis_lock and actual_radius <= WHEEL_DIAMETER_AXIS_LOCK_NEAR_CENTER_RADIUS:
            locked_axis = float(axis_lock['axis_angle'])
            axis_lock_source = axis_lock.get('source') or 'lock'

        if locked_axis is not None:
            axis_angle = normalize_angle_radians(locked_axis)
            projected_radius = dx * math.cos(axis_angle) + dy * math.sin(axis_angle)
            signed_radius = projected_radius
            if (
                handle_signed_radius is not None
                and abs(handle_signed_radius) >= WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS
                and (
                    actual_radius <= WHEEL_ROTATION_MIN_RADIUS
                    or axis_lock_source == trusted_handle_source
                )
            ):
                signed_radius = handle_signed_radius
            elif (
                axis_lock
                and abs(signed_radius) < WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS
                and abs(lock_signed_radius) >= WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS
            ):
                signed_radius = lock_signed_radius
            debug_kind = 'axis_lock'
        else:
            small_axis = wheel_diameter_axis_from_small_vector(dx, dy, actual_radius)
            if small_axis and actual_radius < WHEEL_ROTATION_MIN_RADIUS:
                axis_angle, signed_radius = small_axis
                axis_lock_source = 'small-vector'
                debug_kind = 'small_axis'
            else:
                axis_angle, signed_radius = wheel_diameter_axis_from_vector(dx, dy, actual_radius)

    return {
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'axis_lock_source': axis_lock_source,
        'debug_kind': debug_kind,
        'projected_radius': projected_radius,
        'state_signed_radius': state_signed_radius,
    }


def wheel_diameter_safe_origin_context(
    handle,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    max_radius,
    ticks,
    sensitivity,
):
    start_reference_x = handle['x']
    start_reference_y = handle['y']
    safe_origin_delta = ticks * sensitivity * WHEEL_RADIAL_PIXELS_PER_TICK
    safe_origin_edge_radius = max(
        WHEEL_ROTATION_MIN_RADIUS,
        max_radius * WHEEL_DIAMETER_SAFE_PRESS_ORIGIN_EDGE_RATIO,
    )
    safe_press_allowed = (
        abs(signed_radius) >= safe_origin_edge_radius
        and signed_radius * safe_origin_delta < 0
    )
    if safe_press_allowed:
        press_x, press_y = wheel_diameter_safe_press_point(
            center_x,
            center_y,
            axis_angle,
            signed_radius,
            handle['x'],
            handle['y'],
            max_radius,
        )
    else:
        press_x, press_y = handle['x'], handle['y']

    safe_press_used = math.hypot(press_x - handle['x'], press_y - handle['y']) > 0.5
    safe_origin_inward = safe_press_used and safe_press_allowed
    adjusted_handle = handle
    adjusted_signed_radius = signed_radius
    actual_signed_radius = None
    if safe_origin_inward:
        actual_signed_radius = signed_radius
        safe_signed_radius = (
            (press_x - center_x) * math.cos(axis_angle)
            + (press_y - center_y) * math.sin(axis_angle)
        )
        adjusted_signed_radius = max(-max_radius, min(max_radius, safe_signed_radius))
        start_reference_x = press_x
        start_reference_y = press_y
        adjusted_handle = dict(handle)
        adjusted_handle.update({
            'x': press_x,
            'y': press_y,
            'angle': wheel_diameter_display_angle(axis_angle, adjusted_signed_radius),
            'radial_axis_angle': axis_angle,
            'signed_radius': adjusted_signed_radius,
            'radius': abs(adjusted_signed_radius),
            'source': f"{handle.get('source', 'handle')}_safe_origin",
        })

    return {
        'handle': adjusted_handle,
        'signed_radius': adjusted_signed_radius,
        'press_x': press_x,
        'press_y': press_y,
        'start_reference_x': start_reference_x,
        'start_reference_y': start_reference_y,
        'safe_press_used': safe_press_used,
        'safe_origin_inward': safe_origin_inward,
        'safe_origin_delta': safe_origin_delta,
        'actual_signed_radius': actual_signed_radius,
    }


def wheel_diameter_edge_lock_plan(
    reuse_state,
    state_needs_fresh_handle,
    state,
    ticks,
    sensitivity,
    max_radius,
    effective_max_radius,
    outer_control_radius,
    center_x,
    center_y,
):
    result = {'locked': False}
    if not reuse_state or state_needs_fresh_handle or not state:
        return result

    state_axis_angle = state.get('axis_angle')
    state_signed_radius = state.get('signed_radius')
    state_max_radius = state.get('max_radius') or max_radius
    if effective_max_radius is not None:
        state_max_radius = effective_max_radius
    if state_axis_angle is None or state_signed_radius is None:
        return result

    edge_radius = max(max_radius, abs(state_max_radius))
    requested_state_signed_radius = (
        state_signed_radius
        + ticks * sensitivity * WHEEL_RADIAL_PIXELS_PER_TICK
    )
    if not (
        abs(requested_state_signed_radius) > abs(state_signed_radius) + 0.01
        and abs(state_signed_radius) >= edge_radius - WHEEL_DIAMETER_EDGE_LOCK_EPSILON
    ):
        return result

    locked_signed_radius = math.copysign(edge_radius, state_signed_radius)
    locked_x, locked_y = wheel_diameter_point(
        center_x,
        center_y,
        state_axis_angle,
        locked_signed_radius,
    )
    state_angle = wheel_diameter_display_angle(
        state_axis_angle,
        locked_signed_radius,
    )
    outer_x, outer_y, outer_angle = wheel_diameter_outer_control_point(
        center_x,
        center_y,
        state_axis_angle,
        locked_signed_radius,
        outer_control_radius,
    )
    return {
        'locked': True,
        'axis_angle': state_axis_angle,
        'edge_radius': edge_radius,
        'requested_state_signed_radius': requested_state_signed_radius,
        'locked_signed_radius': locked_signed_radius,
        'locked_x': locked_x,
        'locked_y': locked_y,
        'state_angle': state_angle,
        'outer_x': outer_x,
        'outer_y': outer_y,
        'outer_angle': outer_angle,
    }


__all__ = [
    'wheel_diameter_axis_context',
    'wheel_diameter_axis_lock_for_area',
    'wheel_diameter_edge_lock_plan',
    'wheel_diameter_safe_origin_context',
]
