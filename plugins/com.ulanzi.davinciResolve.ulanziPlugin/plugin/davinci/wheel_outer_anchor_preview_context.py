"""Preview state assembly for outer-anchor wheel rotation."""

import time

from .wheel_anchor_adaptive import resolve_anchor_degrees_per_tick
from .wheel_outer_anchor_logic import outer_anchor_target
from .wheel_state_helpers import resolve_effective_max_radius, resolve_outer_control_radius
from .wheel_visual_radius import build_wheel_outer_visual


def wheel_outer_anchor_preview_context(
    area,
    area_name,
    target_key,
    ticks,
    center_x,
    center_y,
    visual_center_x,
    visual_center_y,
    wheel_radius,
    visual_radius,
    handle_radius,
    actual_radius,
    start_angle,
    state,
    reuse_state,
    previous,
    force_fresh_handle,
    previous_from_diameter,
    no_progress_count,
    wheel_state_for_area_fn,
    commit_wheel_anchor_preview_fn,
    sensitivity,
    pump_overlay_messages_fn=None,
):
    wheel_state = wheel_state_for_area_fn(center_x, center_y, wheel_radius)
    stored_effective_max_radius = resolve_effective_max_radius(
        state if reuse_state else None,
        previous,
        wheel_state,
    )
    adaptive_degrees_per_tick = resolve_anchor_degrees_per_tick(
        state if reuse_state else None,
        previous,
        wheel_state,
        handle_radius=handle_radius,
    )
    target_plan = outer_anchor_target(
        center_x,
        center_y,
        start_angle,
        handle_radius,
        ticks,
        sensitivity,
        degrees_per_tick=adaptive_degrees_per_tick,
    )
    state_angle = target_plan['state_angle']
    target_x = target_plan['target_x']
    target_y = target_plan['target_y']
    stable_previous = None
    if previous and not force_fresh_handle and not previous_from_diameter:
        stable_previous = previous
    stable_outer_control_radius = resolve_outer_control_radius(
        state if reuse_state else None,
        stable_previous,
        wheel_state,
    )

    outer_visual = build_wheel_outer_visual(
        area,
        center_x,
        center_y,
        state_angle,
        handle_radius,
        visual_radius=visual_radius,
        wheel_radius=wheel_radius,
        cached_outer_radius=stable_outer_control_radius,
    )
    outer_control_radius = outer_visual['outer_control_radius']
    outer_x = outer_visual['outer_control_x']
    outer_y = outer_visual['outer_control_y']

    preview_at = time.time()
    commit_wheel_anchor_preview_fn(
        area,
        area_name,
        target_key,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        outer_control_radius,
        outer_x,
        outer_y,
        state_angle,
        handle_radius,
        actual_radius,
        target_x,
        target_y,
        stored_effective_max_radius,
        no_progress_count=no_progress_count,
        state_source='preview',
        store_source='outer_anchor_preview',
        adaptive_degrees_per_tick=adaptive_degrees_per_tick,
        adaptive_handle_radius=handle_radius,
        visual_center_x=visual_center_x,
        visual_center_y=visual_center_y,
        mark_recent=True,
        lock_target=True,
        refresh_overlay=True,
        updated_at=preview_at,
    )
    if pump_overlay_messages_fn:
        pump_overlay_messages_fn()

    return {
        'stored_effective_max_radius': stored_effective_max_radius,
        'target_plan': target_plan,
        'adaptive_degrees_per_tick': adaptive_degrees_per_tick,
        'adaptive_tick_units': abs(ticks * sensitivity),
        'outer_control_radius': outer_control_radius,
        'outer_x': outer_x,
        'outer_y': outer_y,
    }


__all__ = ['wheel_outer_anchor_preview_context']
