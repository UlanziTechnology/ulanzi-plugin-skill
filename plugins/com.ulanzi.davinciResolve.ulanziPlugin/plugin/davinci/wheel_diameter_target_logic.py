"""Target radius and preview planning for diameter push/pull gestures."""

from .config import (
    WHEEL_DIAMETER_CENTER_CROSS_EPSILON,
    WHEEL_DIAMETER_CENTER_FORCE_CROSS_RADIUS,
    WHEEL_DIAMETER_CENTER_FORCE_TARGET_RADIUS,
    WHEEL_DIAMETER_CENTER_TRANSIT_RADIUS,
    WHEEL_DIAMETER_FORCE_CENTER_CROSS_ENABLED,
    WHEEL_RADIAL_PIXELS_PER_TICK,
)
from .wheel_diameter_geometry import (
    wheel_diameter_display_angle,
    wheel_diameter_outer_control_point,
    wheel_diameter_point,
)


def wheel_diameter_preview_radius(
    signed_radius,
    target_signed_radius,
    center_crossing,
    axis_locked=False,
):
    if center_crossing:
        return signed_radius
    return target_signed_radius


def wheel_diameter_target_plan(
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    max_radius,
    outer_control_radius,
    ticks,
    sensitivity,
    axis_locked=False,
):
    radial_delta = ticks * sensitivity * WHEEL_RADIAL_PIXELS_PER_TICK
    requested_signed_radius = signed_radius + radial_delta
    target_signed_radius = max(-max_radius, min(max_radius, requested_signed_radius))
    raw_center_crossing = (
        abs(signed_radius) > WHEEL_DIAMETER_CENTER_CROSS_EPSILON
        and abs(target_signed_radius) > WHEEL_DIAMETER_CENTER_CROSS_EPSILON
        and signed_radius * target_signed_radius < 0
    )
    moving_toward_center = signed_radius * radial_delta < 0
    force_center_crossing = (
        WHEEL_DIAMETER_FORCE_CENTER_CROSS_ENABLED
        and abs(signed_radius) > WHEEL_DIAMETER_CENTER_CROSS_EPSILON
        and moving_toward_center
        and (
            abs(signed_radius) <= WHEEL_DIAMETER_CENTER_FORCE_CROSS_RADIUS
            or abs(target_signed_radius) <= WHEEL_DIAMETER_CENTER_FORCE_TARGET_RADIUS
        )
    )
    center_crossing = raw_center_crossing or force_center_crossing
    if center_crossing and WHEEL_DIAMETER_FORCE_CENTER_CROSS_ENABLED:
        target_sign = 1.0 if radial_delta >= 0 else -1.0
        transit_radius = min(max_radius, WHEEL_DIAMETER_CENTER_TRANSIT_RADIUS)
        if target_signed_radius * target_sign <= 0 or abs(target_signed_radius) < transit_radius:
            target_signed_radius = target_sign * min(max_radius, transit_radius)
        crossing_mode = 'transit'
    elif center_crossing:
        crossing_mode = 'direct'
    else:
        crossing_mode = None

    target_x, target_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        target_signed_radius,
    )
    target_outer_x, target_outer_y, target_control_angle = wheel_diameter_outer_control_point(
        center_x,
        center_y,
        axis_angle,
        target_signed_radius,
        outer_control_radius,
    )
    preview_signed_radius = wheel_diameter_preview_radius(
        signed_radius,
        target_signed_radius,
        center_crossing,
        axis_locked=axis_locked,
    )
    preview_x, preview_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        preview_signed_radius,
    )
    preview_outer_x, preview_outer_y, preview_control_angle = wheel_diameter_outer_control_point(
        center_x,
        center_y,
        axis_angle,
        preview_signed_radius,
        outer_control_radius,
    )
    return {
        'radial_delta': radial_delta,
        'requested_signed_radius': requested_signed_radius,
        'target_signed_radius': target_signed_radius,
        'center_crossing': center_crossing,
        'force_center_crossing': force_center_crossing,
        'crossing_mode': crossing_mode,
        'target_x': target_x,
        'target_y': target_y,
        'target_outer_x': target_outer_x,
        'target_outer_y': target_outer_y,
        'target_control_angle': target_control_angle,
        'preview_signed_radius': preview_signed_radius,
        'preview_x': preview_x,
        'preview_y': preview_y,
        'preview_outer_x': preview_outer_x,
        'preview_outer_y': preview_outer_y,
        'preview_control_angle': preview_control_angle,
    }


def wheel_diameter_target_context(
    area_name,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    max_radius,
    outer_control_radius,
    ticks,
    sensitivity,
    axis_locked=False,
):
    context = wheel_diameter_target_plan(
        center_x,
        center_y,
        axis_angle,
        signed_radius,
        max_radius,
        outer_control_radius,
        ticks,
        sensitivity,
        axis_locked=axis_locked,
    )
    requested_signed_radius = context['requested_signed_radius']
    target_signed_radius = context['target_signed_radius']
    force_center_crossing = context['force_center_crossing']
    crossing_mode = context['crossing_mode']
    if crossing_mode == 'transit':
        context['debug_message'] = (
            f"diameter center-cross transit {area_name} "
            f"actual={signed_radius:.1f} requested={requested_signed_radius:.1f} "
            f"target={target_signed_radius:.1f} forced={force_center_crossing}"
        )
    elif crossing_mode == 'direct':
        context['debug_message'] = (
            f"diameter center-cross direct {area_name} "
            f"actual={signed_radius:.1f} requested={requested_signed_radius:.1f} "
            f"target={target_signed_radius:.1f}"
        )
    else:
        context['debug_message'] = None
    return context


def wheel_diameter_target_commit_context(target_plan, axis_angle, signed_radius, updated_at):
    target_signed_radius = target_plan['target_signed_radius']
    if abs(target_signed_radius - signed_radius) < 0.1:
        return {
            'kind': 'noop',
            'signed_radius': target_signed_radius,
            'x': target_plan['target_x'],
            'y': target_plan['target_y'],
            'outer_x': target_plan['target_outer_x'],
            'outer_y': target_plan['target_outer_y'],
            'control_angle': target_plan['target_control_angle'],
            'state_angle': wheel_diameter_display_angle(axis_angle, target_signed_radius),
            'store_source': 'diameter_noop',
            'updated_at': updated_at,
        }

    preview_signed_radius = target_plan['preview_signed_radius']
    return {
        'kind': 'preview',
        'signed_radius': preview_signed_radius,
        'x': target_plan['preview_x'],
        'y': target_plan['preview_y'],
        'outer_x': target_plan['preview_outer_x'],
        'outer_y': target_plan['preview_outer_y'],
        'control_angle': target_plan['preview_control_angle'],
        'state_angle': wheel_diameter_display_angle(axis_angle, preview_signed_radius),
        'state_source': 'preview',
        'handle_source': 'diameter_preview',
        'store_source': 'diameter_preview',
        'updated_at': updated_at,
    }


__all__ = [
    'wheel_diameter_preview_radius',
    'wheel_diameter_target_commit_context',
    'wheel_diameter_target_context',
    'wheel_diameter_target_plan',
]
