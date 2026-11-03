"""Overlay-state builders for DaVinci color-wheel displays."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_RESET_RADIUS,
    WHEEL_DIAMETER_STATE_SECONDS,
)
from .overlay_colors import _wheel_hue_hex
from .wheel_anchor_reuse_policy import wheel_anchor_is_reusable
from .wheel_diameter_geometry import wheel_diameter_display_angle
from .wheel_visual_radius import build_wheel_outer_visual, wheel_visual_radius


def _area_center(area):
    return (
        area.get('center_x', area['x'] + area['w'] / 2),
        area.get('center_y', area['y'] + area['h'] / 2),
    )


def _visual_center(state, center_x, center_y):
    visual_center_x = state.get('visual_center_x') if state else None
    visual_center_y = state.get('visual_center_y') if state else None
    if visual_center_x is None or visual_center_y is None:
        return center_x, center_y
    return visual_center_x, visual_center_y


def _finite_angle(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _center_display_angle(handle, axis_angle, control_angle):
    """Resolve the full-circle direction remembered by a centered wheel."""

    try:
        axis_x = float(handle.get('last_nonzero_axis_x'))
        axis_y = float(handle.get('last_nonzero_axis_y'))
    except (TypeError, ValueError):
        axis_x = axis_y = None
    if (
        axis_x is not None
        and axis_y is not None
        and math.isfinite(axis_x)
        and math.isfinite(axis_y)
        and math.hypot(axis_x, axis_y) > 1e-6
    ):
        return math.atan2(axis_y, axis_x)

    for candidate in (control_angle, axis_angle, -math.pi / 2):
        candidate = _finite_angle(candidate)
        if candidate is not None:
            return candidate
    return -math.pi / 2


def wheel_overlay_state_from_anchor(area, anchor):
    center_x, center_y = _area_center(area)
    state_center_x = anchor.get('center_x', center_x)
    state_center_y = anchor.get('center_y', center_y)
    visual_center_x, visual_center_y = _visual_center(anchor, state_center_x, state_center_y)
    control_angle = anchor.get('angle', -math.pi / 2)
    return {
        'center_x': state_center_x,
        'center_y': state_center_y,
        'visual_center_x': visual_center_x,
        'visual_center_y': visual_center_y,
        'wheel_radius': wheel_visual_radius(
            area,
            anchor.get('visual_radius') or anchor.get('wheel_radius'),
        ),
        'outer_control_radius': anchor.get('outer_control_radius'),
        'outer_control_x': anchor.get('outer_control_x'),
        'outer_control_y': anchor.get('outer_control_y'),
        'angle': control_angle,
        'control_angle': control_angle,
        'signed_radius': anchor.get('handle_radius', 0.0),
        'color': _wheel_hue_hex(control_angle),
    }


def wheel_overlay_state_from_diameter(area, diameter, handle=None):
    handle = handle or {}
    area_center_x, area_center_y = _area_center(area)
    center_x = diameter.get(
        'center_x',
        handle.get('wheel_center_x', area_center_x),
    )
    center_y = diameter.get(
        'center_y',
        handle.get('wheel_center_y', area_center_y),
    )
    visual_center_x, visual_center_y = _visual_center(
        diameter,
        *(_visual_center(handle, center_x, center_y)),
    )
    wheel_radius = wheel_visual_radius(area, (
        diameter.get('visual_radius')
        or diameter.get('wheel_radius')
        or handle.get('wheel_radius')
    ))
    control_angle = diameter.get('control_angle')
    if control_angle is None:
        control_angle = wheel_diameter_display_angle(
            diameter.get('axis_angle', -math.pi / 2),
            diameter.get('signed_radius', 0.0),
        )
    return {
        'center_x': center_x,
        'center_y': center_y,
        'visual_center_x': visual_center_x,
        'visual_center_y': visual_center_y,
        'wheel_radius': wheel_radius,
        'outer_control_radius': diameter.get('outer_control_radius'),
        'outer_control_x': diameter.get('outer_control_x'),
        'outer_control_y': diameter.get('outer_control_y'),
        'angle': control_angle,
        'control_angle': control_angle,
        'signed_radius': diameter.get('signed_radius', 0.0),
        'color': _wheel_hue_hex(control_angle),
    }


def wheel_overlay_state_from_handle(area, handle=None):
    handle = handle or {}
    area_center_x, area_center_y = _area_center(area)
    center_x = handle.get('wheel_center_x', area_center_x)
    center_y = handle.get('wheel_center_y', area_center_y)
    visual_center_x, visual_center_y = _visual_center(handle, center_x, center_y)
    wheel_radius = handle.get('wheel_radius')
    visual_wheel_radius = wheel_visual_radius(
        area,
        handle.get('visual_radius', wheel_radius),
    )

    signed_radius = handle.get('signed_radius')
    handle_radius = None
    if all(key in handle for key in ('x', 'y')):
        dx = handle['x'] - center_x
        dy = handle['y'] - center_y
        handle_radius = math.hypot(dx, dy)
    axis_angle = handle.get('radial_axis_angle')
    if axis_angle is None:
        axis_angle = handle.get('angle')
    if axis_angle is None and handle_radius is not None:
        axis_angle = math.atan2(dy, dx) if handle_radius >= 2 else -math.pi / 2
        if signed_radius is None:
            signed_radius = handle_radius
    if axis_angle is None:
        axis_angle = -math.pi / 2
    if signed_radius is None:
        signed_radius = handle.get('radius', 0.0)
    try:
        signed_radius = float(signed_radius or 0.0)
    except (TypeError, ValueError):
        signed_radius = 0.0

    handle_source = str(handle.get('source') or '')
    exact_smooth_radius = _finite_angle(handle.get('signed_radius'))
    has_exact_smooth_radius = bool(
        handle_source.startswith('smooth_')
        and exact_smooth_radius is not None
    )
    centered_handle = (
        handle_source == 'center_reset'
        or (
            has_exact_smooth_radius
            and abs(exact_smooth_radius) <= 1e-9
        )
        or (
            not has_exact_smooth_radius
            and handle_radius is not None
            and handle_radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS
        )
    )
    control_angle = handle.get('control_angle')
    if centered_handle:
        signed_radius = 0.0
        display_angle = _center_display_angle(handle, axis_angle, control_angle)
    else:
        display_angle = axis_angle
    if control_angle is None:
        control_angle = wheel_diameter_display_angle(axis_angle, signed_radius)
    outer_visual = build_wheel_outer_visual(
        area,
        center_x,
        center_y,
        display_angle,
        signed_radius,
        visual_radius=visual_wheel_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=handle.get('outer_control_radius'),
    )
    outer_control_radius = outer_visual['outer_control_radius']
    outer_x = outer_visual['outer_control_x']
    outer_y = outer_visual['outer_control_y']
    control_angle = outer_visual['control_angle']
    handle_updates = {
        'visual_radius': visual_wheel_radius,
        'visual_center_x': visual_center_x,
        'visual_center_y': visual_center_y,
        'outer_control_radius': outer_control_radius,
        'outer_control_x': outer_x,
        'outer_control_y': outer_y,
        'control_angle': control_angle,
    }
    if centered_handle:
        handle_updates.update({
            'angle': display_angle,
            'radial_axis_angle': axis_angle,
            'signed_radius': 0.0,
            'radius': 0.0,
        })

    return {
        'state': {
            'visual_invalidated': bool(handle.get('visual_invalidated')),
            'center_x': center_x,
            'center_y': center_y,
            'visual_center_x': visual_center_x,
            'visual_center_y': visual_center_y,
            'wheel_radius': visual_wheel_radius,
            'outer_control_radius': outer_control_radius,
            'outer_control_x': outer_x,
            'outer_control_y': outer_y,
            'angle': display_angle,
            'control_angle': control_angle,
            'signed_radius': signed_radius,
            'color': _wheel_hue_hex(control_angle),
        },
        'handle_updates': handle_updates,
    }


def wheel_overlay_state_for_area(area, area_key, area_name, anchor, diameter, handles, now):
    if not area or area.get('type') != 'wheel':
        return {
            'state': None,
            'handle': None,
            'handle_updates': None,
        }

    handle = handles.get(area_name, {}) if area_name else {}
    if handle.get('visual_invalidated'):
        return {'state': {'visual_invalidated': True},
                'handle': None, 'handle_updates': None}

    if (
        anchor
        and wheel_anchor_is_reusable(anchor, area_key, now, area)
    ):
        return {
            'state': wheel_overlay_state_from_anchor(area, anchor),
            'handle': None,
            'handle_updates': None,
        }

    if (
        diameter
        and diameter.get('target_key') == area_key
        and now - diameter.get('updated_at', 0) <= WHEEL_DIAMETER_STATE_SECONDS
    ):
        handle = handles.get(area_name, {}) if area_name else {}
        return {
            'state': wheel_overlay_state_from_diameter(area, diameter, handle),
            'handle': None,
            'handle_updates': None,
        }

    handle = handles.get(area_name, {}) if area_name else {}
    overlay = wheel_overlay_state_from_handle(area, handle)
    return {
        'state': overlay['state'],
        'handle': handle if area_name and area_name in handles else None,
        'handle_updates': overlay['handle_updates'],
    }


__all__ = [
    'wheel_overlay_state_for_area',
    'wheel_overlay_state_from_anchor',
    'wheel_overlay_state_from_diameter',
    'wheel_overlay_state_from_handle',
]
