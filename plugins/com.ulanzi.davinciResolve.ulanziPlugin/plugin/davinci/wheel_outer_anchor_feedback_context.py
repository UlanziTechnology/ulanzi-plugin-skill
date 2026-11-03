"""Feedback state assembly for outer-anchor wheel rotation."""

from .wheel_anchor_adaptive import (
    anchor_adaptive_log_message,
    update_anchor_degrees_per_tick,
)
from .wheel_outer_anchor_logic import outer_anchor_feedback_update
from .wheel_outer_anchor_logs import (
    wheel_outer_anchor_ignored_feedback_log_message,
    wheel_outer_anchor_no_progress_log_message,
)
from .wheel_visual_radius import build_wheel_outer_visual


def wheel_outer_anchor_feedback_context(
    area,
    area_name,
    center_x,
    center_y,
    start_angle,
    state_angle,
    handle_radius,
    actual_radius,
    no_progress_count,
    near_center_anchor,
    feedback_handle,
    visual_radius,
    wheel_radius,
    outer_control_radius,
    outer_x,
    outer_y,
    adaptive_degrees_per_tick,
    adaptive_tick_units,
    source,
    debug_slow_fn=None,
):
    predicted_state_angle = state_angle
    feedback_update = outer_anchor_feedback_update(
        center_x,
        center_y,
        start_angle,
        state_angle,
        handle_radius,
        actual_radius,
        no_progress_count,
        near_center_anchor,
        feedback_handle,
        handle_active=handle_radius >= 1.0,
    )
    adaptive_update = update_anchor_degrees_per_tick(
        adaptive_degrees_per_tick,
        start_angle,
        predicted_state_angle,
        feedback_update,
        adaptive_tick_units,
        source,
    )
    if debug_slow_fn and feedback_update['feedback_accepted']:
        debug_slow_fn(anchor_adaptive_log_message(
            area_name,
            source,
            adaptive_degrees_per_tick,
            adaptive_update,
        ))
    state_angle = feedback_update['state_angle']
    state_handle_x = feedback_update['state_handle_x']
    state_handle_y = feedback_update['state_handle_y']
    state_actual_radius = feedback_update['state_actual_radius']
    next_no_progress_count = feedback_update['next_no_progress_count']

    if debug_slow_fn and feedback_update['no_progress']:
        debug_slow_fn(wheel_outer_anchor_no_progress_log_message(
            area_name,
            feedback_update['requested_angle_delta'],
            feedback_update['feedback_angle_delta'],
            next_no_progress_count,
            feedback_update.get('force_fresh_handle', False),
        ))
    elif debug_slow_fn and feedback_update['feedback_ignored']:
        debug_slow_fn(wheel_outer_anchor_ignored_feedback_log_message(
            area_name,
            state_angle,
            feedback_update['feedback_angle'],
            feedback_update['feedback_angle_error'],
            feedback_update['feedback_angle_limit_degrees'],
            feedback_update['feedback_radius'],
            feedback_update.get('feedback_radius_delta'),
            feedback_update.get('feedback_reject_reason'),
            feedback_update.get('force_fresh_handle', False),
        ))

    if feedback_update['feedback_accepted']:
        outer_visual = build_wheel_outer_visual(
            area,
            center_x,
            center_y,
            state_angle,
            handle_radius,
            visual_radius=visual_radius,
            wheel_radius=wheel_radius,
            cached_outer_radius=outer_control_radius,
        )
        outer_control_radius = outer_visual['outer_control_radius']
        outer_x = outer_visual['outer_control_x']
        outer_y = outer_visual['outer_control_y']

    return {
        'state_angle': state_angle,
        'state_handle_x': state_handle_x,
        'state_handle_y': state_handle_y,
        'state_handle_radius': handle_radius,
        'state_actual_radius': state_actual_radius,
        'next_no_progress_count': next_no_progress_count,
        'feedback_accepted': feedback_update['feedback_accepted'],
        'force_fresh_handle': feedback_update.get('force_fresh_handle', False),
        'outer_control_radius': outer_control_radius,
        'outer_x': outer_x,
        'outer_y': outer_y,
        'adaptive_degrees_per_tick': adaptive_update['degrees_per_tick'],
    }


__all__ = ['wheel_outer_anchor_feedback_context']
