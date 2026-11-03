"""Press-point and axis preparation for wheel diameter gestures."""

import math

from .wheel_diameter_logic import (
    wheel_diameter_axis_context,
    wheel_diameter_safe_origin_context,
)


def wheel_diameter_axis_press_context(
    area,
    area_name,
    handle,
    center_x,
    center_y,
    max_radius,
    reuse_state,
    state,
    state_needs_fresh_handle,
    used_cached_handle,
    ticks,
    axis_lock_fn,
    sensitivity,
    debug_slow_fn=None,
):
    dx = handle['x'] - center_x
    dy = handle['y'] - center_y
    actual_radius = math.hypot(dx, dy)
    axis_lock = axis_lock_fn(center_x, center_y)
    axis_context = wheel_diameter_axis_context(
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
    )
    axis_angle = axis_context['axis_angle']
    signed_radius = axis_context['signed_radius']
    axis_lock_source = axis_context['axis_lock_source']
    if debug_slow_fn and axis_context['debug_kind'] == 'outer_state_lock':
        debug_slow_fn(
            f"diameter outer state lock {area_name} "
            f"state={axis_context['state_signed_radius']:.1f} "
            f"detected={axis_context['projected_radius']:.1f}"
        )
    elif debug_slow_fn and axis_context['debug_kind'] == 'axis_lock':
        debug_slow_fn(
            f"diameter axis lock {area_name} source={axis_lock_source} "
            f"axis={math.degrees(axis_angle):.1f} radius={actual_radius:.1f} "
            f"signed={signed_radius:.1f}"
        )
    elif debug_slow_fn and axis_context['debug_kind'] == 'small_axis':
        debug_slow_fn(
            f"diameter small axis {area_name} "
            f"axis={math.degrees(axis_angle):.1f} radius={actual_radius:.1f} "
            f"signed={signed_radius:.1f}"
        )

    signed_radius = max(-max_radius, min(max_radius, signed_radius))
    safe_origin = wheel_diameter_safe_origin_context(
        handle,
        center_x,
        center_y,
        axis_angle,
        signed_radius,
        max_radius,
        ticks,
        sensitivity,
    )
    handle = safe_origin['handle']
    signed_radius = safe_origin['signed_radius']
    confirmed_signed_radius = safe_origin['actual_signed_radius']
    if confirmed_signed_radius is None:
        confirmed_signed_radius = signed_radius
    if debug_slow_fn and safe_origin['safe_origin_inward']:
        debug_slow_fn(
            f"diameter safe origin {area_name} "
            f"actual={safe_origin['actual_signed_radius']:.1f} "
            f"start={signed_radius:.1f} "
            f"delta={safe_origin['safe_origin_delta']:.1f}"
        )

    return {
        'handle': handle,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'confirmed_signed_radius': confirmed_signed_radius,
        'axis_lock_source': axis_lock_source,
        'press_x': safe_origin['press_x'],
        'press_y': safe_origin['press_y'],
        'start_reference_x': safe_origin['start_reference_x'],
        'start_reference_y': safe_origin['start_reference_y'],
        'safe_press_used': safe_origin['safe_press_used'],
    }


__all__ = ['wheel_diameter_axis_press_context']
