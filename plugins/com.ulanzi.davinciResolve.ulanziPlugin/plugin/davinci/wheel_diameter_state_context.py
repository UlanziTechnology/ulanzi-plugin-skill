"""State reuse helpers for diameter push/pull wheel gestures."""

import math

from .config import WHEEL_DIAMETER_STATE_SECONDS, WHEEL_HANDLE_CACHE_SECONDS
from .wheel_anchor_reuse_policy import wheel_anchor_is_reusable
from .wheel_diameter_geometry import (
    wheel_diameter_display_angle,
    wheel_diameter_point,
)
from .wheel_state_helpers import (
    clamp_max_radius_with_effective,
    resolve_effective_max_radius,
)
from .wheel_visual_radius import (
    resolve_wheel_outer_control_radius,
    wheel_visual_radius,
)


def wheel_diameter_reuse_state(state, target_key, now):
    return bool(
        state
        and state.get('target_key') == target_key
        and now - state.get('updated_at', 0) <= WHEEL_DIAMETER_STATE_SECONDS
    )


def wheel_diameter_state_needs_fresh_handle(state, reuse_state):
    return bool(reuse_state and state and state.get('needs_fresh_handle'))


def wheel_diameter_previous_handle_info(previous, now):
    has_handle = bool(
        previous
        and all(key in previous for key in ('x', 'y', 'wheel_center_x', 'wheel_center_y'))
    )
    recent = bool(
        has_handle
        and now - previous.get('updated_at', 0) <= WHEEL_HANDLE_CACHE_SECONDS
    )
    return has_handle, recent


def wheel_diameter_reuse_anchor(anchor, target_key, now, area=None):
    return wheel_anchor_is_reusable(anchor, target_key, now, area)


def wheel_diameter_handle_from_state(state, now):
    if not state or not all(
        key in state for key in ('center_x', 'center_y', 'axis_angle', 'signed_radius')
    ):
        return None

    center_x = state['center_x']
    center_y = state['center_y']
    axis_angle = state['axis_angle']
    signed_radius = state.get('signed_radius', 0.0)
    x, y = wheel_diameter_point(center_x, center_y, axis_angle, signed_radius)
    angle = wheel_diameter_display_angle(axis_angle, signed_radius)
    return {
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'visual_center_x': state.get('visual_center_x'),
        'visual_center_y': state.get('visual_center_y'),
        'wheel_radius': state.get('wheel_radius'),
        'visual_radius': state.get('visual_radius'),
        'x': x,
        'y': y,
        'angle': angle,
        'radial_axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'radius': abs(signed_radius),
        'effective_max_radius': state.get('effective_max_radius'),
        'outer_control_radius': state.get('outer_control_radius'),
        'outer_control_x': state.get('outer_control_x'),
        'outer_control_y': state.get('outer_control_y'),
        'control_angle': state.get('control_angle', angle),
        'source': 'diameter_state',
        'updated_at': state.get('updated_at', now),
    }


def wheel_diameter_handle_from_anchor(anchor, area, now):
    if not anchor:
        return None

    center_x = anchor.get('center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = anchor.get('center_y', area.get('center_y', area['y'] + area['h'] / 2))
    axis_angle = anchor.get('angle', -math.pi / 2)
    radius = anchor.get('handle_radius', anchor.get('signed_radius', 0.0))
    radius = max(0.0, float(radius or 0.0))
    x = center_x + math.cos(axis_angle) * radius
    y = center_y + math.sin(axis_angle) * radius
    return {
        'wheel_center_x': center_x,
        'wheel_center_y': center_y,
        'visual_center_x': anchor.get('visual_center_x'),
        'visual_center_y': anchor.get('visual_center_y'),
        'wheel_radius': anchor.get('wheel_radius'),
        'visual_radius': anchor.get('visual_radius'),
        'x': x,
        'y': y,
        'angle': axis_angle,
        'radial_axis_angle': axis_angle,
        'signed_radius': radius,
        'radius': radius,
        'effective_max_radius': anchor.get('effective_max_radius'),
        'outer_control_radius': anchor.get('outer_control_radius'),
        'outer_control_x': anchor.get('outer_control_x'),
        'outer_control_y': anchor.get('outer_control_y'),
        'control_angle': anchor.get('angle', axis_angle),
        'source': 'diameter_anchor',
        'updated_at': anchor.get('updated_at', now),
    }


def wheel_diameter_initial_cached_handle(
    state,
    reuse_state,
    state_needs_fresh_handle,
    previous,
    previous_has_handle,
    previous_recent_handle,
    anchor,
    reuse_anchor,
    area,
    now,
):
    handle = None
    state_handle = None
    used_cached_handle = False
    drag_source = 'detected'
    fresh_handle_required = False

    if reuse_state:
        if not state_needs_fresh_handle and previous_has_handle:
            handle = dict(previous)
            used_cached_handle = True
            drag_source = 'state'
        else:
            state_handle = (
                None
                if state_needs_fresh_handle
                else wheel_diameter_handle_from_state(state, now)
            )
        if not handle and state_handle:
            handle = state_handle
            used_cached_handle = True
            drag_source = 'state'
        elif not handle and state_needs_fresh_handle:
            fresh_handle_required = True

    if not handle and reuse_anchor and not state_needs_fresh_handle:
        handle = wheel_diameter_handle_from_anchor(anchor, area, now)
        used_cached_handle = True
        drag_source = 'anchor'

    if not handle and previous_recent_handle and not state_needs_fresh_handle:
        handle = dict(previous)
        used_cached_handle = True
        drag_source = 'cached'

    return {
        'handle': handle,
        'used_cached_handle': used_cached_handle,
        'drag_source': drag_source,
        'fresh_handle_required': fresh_handle_required,
    }


def wheel_diameter_cached_handle_context(state, target_key, now, previous, anchor, area):
    reuse_state = wheel_diameter_reuse_state(state, target_key, now)
    state_needs_fresh_handle = wheel_diameter_state_needs_fresh_handle(
        state,
        reuse_state,
    )
    previous_has_handle, previous_recent_handle = (
        wheel_diameter_previous_handle_info(previous, now)
    )
    reuse_anchor = wheel_diameter_reuse_anchor(anchor, target_key, now, area)
    cached_handle = wheel_diameter_initial_cached_handle(
        state,
        reuse_state,
        state_needs_fresh_handle,
        previous,
        previous_has_handle,
        previous_recent_handle,
        anchor,
        reuse_anchor,
        area,
        now,
    )
    return {
        'reuse_state': reuse_state,
        'state_needs_fresh_handle': state_needs_fresh_handle,
        'previous_has_handle': previous_has_handle,
        'previous_recent_handle': previous_recent_handle,
        'reuse_anchor': reuse_anchor,
        'handle': cached_handle['handle'],
        'used_cached_handle': cached_handle['used_cached_handle'],
        'drag_source': cached_handle['drag_source'],
        'fresh_handle_required': cached_handle['fresh_handle_required'],
    }


def wheel_diameter_reuse_drag_context(drag, area, wheel_state=None):
    center_x = drag['center_x']
    center_y = drag['center_y']
    wheel_radius = drag.get('wheel_radius')
    max_radius = drag['max_radius']
    effective_max_radius = resolve_effective_max_radius(drag, wheel_state)
    max_radius = clamp_max_radius_with_effective(max_radius, effective_max_radius)
    axis_angle = drag['axis_angle']
    signed_radius = drag.get('signed_radius', 0.0)
    confirmed_signed_radius = drag.get('confirmed_signed_radius', signed_radius)
    visual_radius = wheel_visual_radius(area, wheel_radius)
    outer_control_radius = resolve_wheel_outer_control_radius(
        area,
        center_x,
        center_y,
        visual_radius=visual_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=drag.get('outer_control_radius'),
    )
    start_reference_x = drag.get('predicted_handle_x', drag['x'])
    start_reference_y = drag.get('predicted_handle_y', drag['y'])
    return {
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'visual_center_x': drag.get('visual_center_x'),
        'visual_center_y': drag.get('visual_center_y'),
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'confirmed_signed_radius': confirmed_signed_radius,
        'visual_radius': visual_radius,
        'outer_control_radius': outer_control_radius,
        'start_reference_x': start_reference_x,
        'start_reference_y': start_reference_y,
        'axis_lock_source': drag.get('axis_lock_source'),
        'drag_source': 'dragging',
        'drag_updates': {
            'logical_start_x': start_reference_x,
            'logical_start_y': start_reference_y,
            'safe_press_used': drag.get('safe_press_used', False),
        },
    }


__all__ = [
    'wheel_diameter_cached_handle_context',
    'wheel_diameter_handle_from_anchor',
    'wheel_diameter_handle_from_state',
    'wheel_diameter_initial_cached_handle',
    'wheel_diameter_previous_handle_info',
    'wheel_diameter_reuse_anchor',
    'wheel_diameter_reuse_drag_context',
    'wheel_diameter_reuse_state',
    'wheel_diameter_state_needs_fresh_handle',
]
