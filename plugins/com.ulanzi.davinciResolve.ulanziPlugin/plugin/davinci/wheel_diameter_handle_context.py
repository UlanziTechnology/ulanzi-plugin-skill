"""Initial handle and geometry preparation for wheel diameter gestures."""

from .wheel_diameter_geometry_context import (
    wheel_diameter_center_detection_fallback,
    wheel_diameter_center_state_fallback,
    wheel_diameter_fresh_center_context,
    wheel_diameter_fresh_projection_context,
    wheel_diameter_geometry_context,
    wheel_diameter_replaced_geometry_context,
)
from .wheel_diameter_state_context import wheel_diameter_cached_handle_context
from .wheel_fallback_handle import make_center_fallback_handle
from .wheel_visual_radius import resolve_wheel_outer_control_radius


def wheel_diameter_initial_handle_context(
    area,
    area_name,
    target_key,
    now,
    detect_wheel_circle_in_area_fn,
    detect_handle_fn,
    detect_handle_raw_for_area_fn,
    wheel_diameter_state_fn,
    wheel_handle_for_area_fn,
    wheel_anchor_state_fn,
    debug_slow_fn=None,
):
    state = wheel_diameter_state_fn()
    previous = wheel_handle_for_area_fn(area_name)
    anchor = wheel_anchor_state_fn()
    cached_context = wheel_diameter_cached_handle_context(
        state,
        target_key,
        now,
        previous,
        anchor,
        area,
    )
    reuse_state = cached_context['reuse_state']
    state_needs_fresh_handle = cached_context['state_needs_fresh_handle']
    previous_has_handle = cached_context['previous_has_handle']
    handle = cached_context['handle']
    used_cached_handle = cached_context['used_cached_handle']
    drag_source = cached_context['drag_source']
    if cached_context['fresh_handle_required'] and debug_slow_fn:
        debug_slow_fn(f"diameter fresh handle required {area_name}")

    if not handle:
        handle = detect_handle_raw_for_area_fn(area)
        drag_source = (
            'fresh-detected'
            if handle and state_needs_fresh_handle
            else ('detected' if handle else drag_source)
        )
    if not handle:
        handle = detect_handle_fn(area_name)
        drag_source = (
            'fresh-detect-handle'
            if handle and state_needs_fresh_handle
            else ('detect-handle' if handle else drag_source)
        )
    if not handle and reuse_state and previous_has_handle:
        handle = dict(previous)
        used_cached_handle = True
        drag_source = 'state-stale'
    if not handle and previous_has_handle:
        handle = dict(previous)
        used_cached_handle = True
        drag_source = 'cached-stale'
    if not handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        handle = make_center_fallback_handle(
            area,
            wheel_geometry,
            source='diameter_center_fallback',
        )
        used_cached_handle = bool(handle)
        drag_source = 'center-fallback' if handle else drag_source

    return {
        'state': state,
        'previous': previous,
        'anchor': anchor,
        'reuse_state': reuse_state,
        'state_needs_fresh_handle': state_needs_fresh_handle,
        'previous_has_handle': previous_has_handle,
        'handle': handle,
        'used_cached_handle': used_cached_handle,
        'drag_source': drag_source,
    }


def wheel_diameter_geometry_from_handle_context(
    area,
    area_name,
    handle,
    state,
    previous,
    previous_has_handle,
    reuse_state,
    state_needs_fresh_handle,
    used_cached_handle,
    wheel_state_for_area_fn,
    detect_wheel_circle_in_area_fn,
    debug_slow_fn=None,
):
    if 'wheel_center_x' not in handle or 'wheel_center_y' not in handle or 'wheel_radius' not in handle:
        wheel_geometry = detect_wheel_circle_in_area_fn(area)
        if wheel_geometry:
            handle.update(wheel_geometry)

    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    fresh_center = wheel_diameter_fresh_center_context(
        handle,
        area,
        state,
        center_x,
        center_y,
        reuse_state,
        state_needs_fresh_handle,
    )
    handle = fresh_center['handle']
    center_x = fresh_center['center_x']
    center_y = fresh_center['center_y']

    center_fallback = wheel_diameter_center_detection_fallback(
        handle,
        previous,
        previous_has_handle,
        reuse_state,
        used_cached_handle,
        state_needs_fresh_handle,
        state,
        center_x,
        center_y,
    )
    handle = center_fallback['handle']
    center_x = center_fallback['center_x']
    center_y = center_fallback['center_y']
    used_cached_handle = center_fallback['used_cached_handle']
    wheel_radius = handle.get('wheel_radius')
    wheel_state = wheel_state_for_area_fn(center_x, center_y, wheel_radius)
    geometry_context = wheel_diameter_geometry_context(
        area,
        handle,
        state=state,
        reuse_state=reuse_state,
        previous=previous,
        wheel_state=wheel_state,
    )
    center_x = geometry_context['center_x']
    center_y = geometry_context['center_y']
    wheel_radius = geometry_context['wheel_radius']
    max_radius = geometry_context['max_radius']
    effective_max_radius = geometry_context['effective_max_radius']
    visual_radius = geometry_context['visual_radius']
    outer_control_radius = geometry_context['outer_control_radius']

    center_state = wheel_diameter_center_state_fallback(
        handle,
        previous,
        previous_has_handle,
        reuse_state,
        state_needs_fresh_handle,
        state,
        center_x,
        center_y,
        used_cached_handle,
    )
    if center_state['replaced']:
        handle = center_state['handle']
        used_cached_handle = center_state['used_cached_handle']
        replaced_geometry = wheel_diameter_replaced_geometry_context(
            area,
            handle,
            effective_max_radius,
            outer_control_radius,
        )
        center_x = replaced_geometry['center_x']
        center_y = replaced_geometry['center_y']
        wheel_radius = replaced_geometry['wheel_radius']
        max_radius = replaced_geometry['max_radius']
        visual_radius = replaced_geometry['visual_radius']
        outer_control_radius = replaced_geometry['outer_control_radius']
    else:
        outer_control_radius = resolve_wheel_outer_control_radius(
            area,
            center_x,
            center_y,
            visual_radius=visual_radius,
            wheel_radius=wheel_radius,
            cached_outer_radius=outer_control_radius,
        )

    fresh_projection = wheel_diameter_fresh_projection_context(
        handle,
        center_x,
        center_y,
        max_radius,
        reuse_state,
        state_needs_fresh_handle,
        state,
    )
    if fresh_projection['projected']:
        handle = fresh_projection['handle']
        if debug_slow_fn:
            debug_slow_fn(
                f"diameter fresh projected {area_name} "
                f"actual={fresh_projection['projected_signed_radius']:.1f} "
                f"cross={fresh_projection['projected_cross']:.1f} "
                f"raw=({fresh_projection['raw_x']:.0f}, {fresh_projection['raw_y']:.0f}) "
                f"projected=({handle['x']:.0f}, {handle['y']:.0f})"
            )

    return {
        'handle': handle,
        'center_x': center_x,
        'center_y': center_y,
        'wheel_radius': wheel_radius,
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'visual_radius': visual_radius,
        'outer_control_radius': outer_control_radius,
        'used_cached_handle': used_cached_handle,
    }


__all__ = [
    'wheel_diameter_geometry_from_handle_context',
    'wheel_diameter_initial_handle_context',
]
