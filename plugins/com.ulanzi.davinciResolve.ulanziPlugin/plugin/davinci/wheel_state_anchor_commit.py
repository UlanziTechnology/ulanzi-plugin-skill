"""Outer-anchor wheel state commit helpers."""

import math
import time

from .area_target_helpers import area_key
from .wheel_state_accessors import (
    lock_wheel_target,
    mark_recent_wheel_area,
    wheel_state_for_area,
)
from .wheel_state_handle_payloads import wheel_handle_payload
from .wheel_state_helpers import resolve_effective_max_radius, resolve_outer_control_radius
from .wheel_state_anchor_payloads import wheel_anchor_state_payload
from .wheel_state_store_bridge import (
    commit_wheel_capability_to_store,
    refresh_wheel_overlay_from_state_manager,
)
from .wheel_visual_radius import build_wheel_outer_visual, resolve_wheel_outer_control_radius


def _visual_center_from_source(source):
    if not isinstance(source, dict):
        return None, None
    visual_center_x = source.get('visual_center_x')
    visual_center_y = source.get('visual_center_y')
    if visual_center_x is None or visual_center_y is None:
        return None, None
    return visual_center_x, visual_center_y


def _resolve_visual_center(manager, area, area_name, center_x, center_y, wheel_radius, preferred=None):
    for source in (
        preferred,
        wheel_state_for_area(manager, area, center_x, center_y, wheel_radius),
        manager.handles.get(area_name, {}),
    ):
        visual_center_x, visual_center_y = _visual_center_from_source(source)
        if visual_center_x is not None and visual_center_y is not None:
            return visual_center_x, visual_center_y
    return None, None


def commit_wheel_anchor_state(
    manager,
    area,
    area_name,
    target_key,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    outer_control_radius,
    outer_control_x,
    outer_control_y,
    angle,
    handle_radius,
    actual_radius,
    handle_x,
    handle_y,
    effective_max_radius,
    *,
    no_progress_count=0,
    state_source=None,
    store_source=None,
    adaptive_degrees_per_tick=None,
    adaptive_handle_radius=None,
    force_fresh_handle=None,
    last_detected_handle=None,
    visual_center_x=None,
    visual_center_y=None,
    commit_handle=True,
    mark_recent=False,
    lock_target=False,
    refresh_overlay=False,
    updated_at=None,
):
    updated_at = time.time() if updated_at is None else updated_at
    state_kwargs = {}
    if state_source is not None:
        state_kwargs['source'] = state_source
    if adaptive_degrees_per_tick is not None:
        state_kwargs['adaptive_degrees_per_tick'] = adaptive_degrees_per_tick
    if adaptive_handle_radius is not None:
        state_kwargs['adaptive_handle_radius'] = adaptive_handle_radius
    if force_fresh_handle is not None:
        state_kwargs['force_fresh_handle'] = bool(force_fresh_handle)
    preferred_visual_center = None
    if visual_center_x is not None and visual_center_y is not None:
        preferred_visual_center = {
            'visual_center_x': visual_center_x,
            'visual_center_y': visual_center_y,
        }
    resolved_visual_center_x, resolved_visual_center_y = _resolve_visual_center(
        manager,
        area,
        area_name,
        center_x,
        center_y,
        wheel_radius,
        preferred=preferred_visual_center or last_detected_handle,
    )
    visual_center_kwargs = {}
    if resolved_visual_center_x is not None and resolved_visual_center_y is not None:
        visual_center_kwargs.update({
            'visual_center_x': resolved_visual_center_x,
            'visual_center_y': resolved_visual_center_y,
        })
    state = wheel_anchor_state_payload(
        target_key,
        area_name,
        area,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        outer_control_radius,
        outer_control_x,
        outer_control_y,
        angle,
        handle_radius,
        actual_radius,
        handle_x,
        handle_y,
        effective_max_radius,
        no_progress_count=no_progress_count,
        updated_at=updated_at,
        **visual_center_kwargs,
        **state_kwargs,
    )
    manager._wheel_anchor_state = state
    if commit_handle:
        handle_kwargs = {}
        if adaptive_degrees_per_tick is not None:
            handle_kwargs['adaptive_degrees_per_tick'] = adaptive_degrees_per_tick
        if adaptive_handle_radius is not None:
            handle_kwargs['adaptive_handle_radius'] = adaptive_handle_radius
        handle_kwargs.update(visual_center_kwargs)
        manager.handles[area_name] = wheel_handle_payload(
            center_x,
            center_y,
            wheel_radius,
            handle_x,
            handle_y,
            angle,
            angle,
            handle_radius,
            visual_radius=visual_radius,
            effective_max_radius=effective_max_radius,
            outer_control_radius=outer_control_radius,
            outer_control_x=outer_control_x,
            outer_control_y=outer_control_y,
            control_angle=angle,
            updated_at=updated_at,
            **handle_kwargs,
        )
    commit_wheel_capability_to_store(
        manager,
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        visual_radius=visual_radius,
        visual_center_x=resolved_visual_center_x,
        visual_center_y=resolved_visual_center_y,
        effective_max_radius=effective_max_radius,
        outer_control_radius=outer_control_radius,
        last_detected_handle=last_detected_handle,
        source=store_source,
    )
    if mark_recent:
        mark_recent_wheel_area(manager, area, updated_at=updated_at)
    if lock_target:
        lock_wheel_target(manager, area, updated_at=updated_at)
    if refresh_overlay:
        refresh_wheel_overlay_from_state_manager(manager, area)
    return state


def seed_wheel_anchor_state_from_overlay(
    manager,
    area,
    state=None,
    source='overlay',
    overlay_state_fn=None,
    debug_slow_fn=None,
):
    if not area or area.get('type') != 'wheel':
        return False

    area_name = area.get('name')
    target_key = area_key(area)
    if not area_name or not target_key:
        return False

    if state is None and overlay_state_fn:
        state = overlay_state_fn(area)
    if not state:
        return False

    center_x = state.get('center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = state.get('center_y', area.get('center_y', area['y'] + area['h'] / 2))
    angle = state.get('control_angle', state.get('angle', -math.pi / 2))
    signed_radius = state.get('signed_radius', 0.0)
    try:
        handle_radius = abs(float(signed_radius))
    except (TypeError, ValueError):
        handle_radius = 0.0

    handle = manager.handles.get(area_name, {})
    actual_radius = handle_radius
    if all(key in handle for key in ('x', 'y')):
        actual_radius = math.hypot(
            float(handle['x']) - float(center_x),
            float(handle['y']) - float(center_y),
        )
        if handle_radius <= 0.0:
            handle_radius = actual_radius

    if handle_radius <= 0.0 and actual_radius <= 0.0:
        return False

    wheel_radius = handle.get('wheel_radius') or state.get('wheel_radius')
    visual_radius = state.get('wheel_radius') or handle.get('visual_radius') or wheel_radius
    wheel_state = wheel_state_for_area(manager, area, center_x, center_y, wheel_radius)
    effective_max_radius = resolve_effective_max_radius(handle, state, wheel_state)
    outer_control_radius = resolve_outer_control_radius(state, wheel_state)
    if outer_control_radius is None:
        outer_control_radius = resolve_wheel_outer_control_radius(
            area,
            center_x,
            center_y,
            visual_radius=visual_radius,
            wheel_radius=wheel_radius,
        )
    outer_control_x = state.get('outer_control_x')
    outer_control_y = state.get('outer_control_y')
    if outer_control_x is None or outer_control_y is None:
        outer_visual = build_wheel_outer_visual(
            area,
            center_x,
            center_y,
            angle,
            handle_radius,
            visual_radius=visual_radius,
            wheel_radius=wheel_radius,
            cached_outer_radius=outer_control_radius,
        )
        outer_control_radius = outer_visual['outer_control_radius']
        outer_control_x = outer_visual['outer_control_x']
        outer_control_y = outer_visual['outer_control_y']

    updated_at = time.time()
    handle_x = center_x + math.cos(angle) * handle_radius
    handle_y = center_y + math.sin(angle) * handle_radius
    commit_wheel_anchor_state(
        manager,
        area,
        area_name,
        target_key,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        outer_control_radius,
        outer_control_x,
        outer_control_y,
        angle,
        handle_radius,
        actual_radius,
        handle_x,
        handle_y,
        effective_max_radius,
        state_source=source,
        store_source=f"anchor_seed_{source}",
        commit_handle=False,
        updated_at=updated_at,
    )
    if debug_slow_fn:
        debug_slow_fn(
            f"wheel anchor seeded {area_name} source={source} "
            f"angle={math.degrees(angle):.1f} "
            f"handle_radius={handle_radius:.1f} actual_radius={actual_radius:.1f} "
            f"visual_radius={float(visual_radius or 0):.1f} "
            f"outer_radius={float(outer_control_radius or 0):.1f}"
        )
    return True


__all__ = [
    'commit_wheel_anchor_state',
    'seed_wheel_anchor_state_from_overlay',
]
