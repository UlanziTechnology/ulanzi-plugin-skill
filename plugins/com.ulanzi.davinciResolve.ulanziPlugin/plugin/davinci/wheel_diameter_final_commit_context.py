"""Final state commit helper for wheel diameter gestures."""

import time

from .wheel_state_diameter_payloads import wheel_diameter_drag_final_payload


def wheel_diameter_commit_final_result(
    area,
    area_name,
    target_key,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    outer_control_radius,
    axis_angle,
    final_context,
    cursor_end_x,
    cursor_end_y,
    last_detected_handle,
    drag,
    release_wheel_drag_fn,
    commit_wheel_diameter_state_fn,
    set_wheel_diameter_axis_lock_fn,
):
    final_at = time.time()
    final_signed_radius = final_context['final_signed_radius']
    final_x = final_context['final_x']
    final_y = final_context['final_y']
    max_radius = final_context['max_radius']
    effective_max_radius = final_context['effective_max_radius']
    state_angle = final_context['state_angle']
    final_outer_x = final_context['final_outer_x']
    final_outer_y = final_context['final_outer_y']
    final_control_angle = final_context['final_control_angle']
    center_cross_unconfirmed = final_context['center_cross_unconfirmed']
    state_source = final_context['state_source']
    feedback_confirmed = final_context.get('feedback_confirmed', True)
    needs_fresh_handle = final_context.get(
        'needs_fresh_handle',
        center_cross_unconfirmed,
    )
    confirmed_detected_handle = (
        last_detected_handle if feedback_confirmed else None
    )

    commit_wheel_diameter_state_fn(
        area,
        area_name,
        target_key,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        axis_angle,
        final_signed_radius,
        max_radius,
        effective_max_radius,
        outer_control_radius,
        final_outer_x,
        final_outer_y,
        final_control_angle,
        final_x,
        final_y,
        state_angle,
        state_source=state_source,
        store_source=state_source,
        last_detected_handle=confirmed_detected_handle,
        needs_fresh_handle=needs_fresh_handle,
        commit_handle=True,
        update_stale_handle_metadata=False,
        mark_recent=True,
        updated_at=final_at,
    )
    drag.update(wheel_diameter_drag_final_payload(
        cursor_end_x,
        cursor_end_y,
        axis_angle,
        final_signed_radius,
        effective_max_radius,
        final_x,
        final_y,
        outer_control_radius,
        final_outer_x,
        final_outer_y,
        final_control_angle,
        updated_at=final_at,
    ))
    set_wheel_diameter_axis_lock_fn(
        area,
        center_x,
        center_y,
        axis_angle,
        final_signed_radius,
        source='diameter_final',
        allow_center=True,
    )
    if needs_fresh_handle or not drag.get('button_down', True):
        release_wheel_drag_fn()


__all__ = ['wheel_diameter_commit_final_result']
