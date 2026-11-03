"""Final feedback reconciliation for wheel diameter gestures."""

from .wheel_diameter_final_logic import (
    wheel_diameter_final_commit_context,
)
from .wheel_diameter_center_finalization import wheel_diameter_apply_center_finalization
from .wheel_diameter_edge_finalization import wheel_diameter_apply_edge_hold
from .wheel_diameter_outer_limit_learning import wheel_diameter_apply_outer_limit_learning


def wheel_diameter_finalize_after_feedback(
    area,
    area_name,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    outer_control_radius,
    axis_angle,
    signed_radius,
    target_signed_radius,
    final_signed_radius,
    final_x,
    final_y,
    max_radius,
    effective_max_radius,
    moved,
    feedback_accepted,
    feedback_signed_radius,
    feedback_action,
    center_crossing,
    drag,
    target_x,
    target_y,
    last_detected_handle,
    commit_wheel_capability_to_store_fn,
    debug_slow_fn=None,
):
    learned_limit = wheel_diameter_apply_outer_limit_learning(
        area,
        area_name,
        center_x,
        center_y,
        wheel_radius,
        visual_radius,
        outer_control_radius,
        moved and feedback_accepted,
        signed_radius,
        target_signed_radius,
        final_signed_radius,
        max_radius,
        effective_max_radius,
        last_detected_handle,
        commit_wheel_capability_to_store_fn,
        debug_slow_fn,
    )
    max_radius = learned_limit['max_radius']
    effective_max_radius = learned_limit['effective_max_radius']

    edge_hold = wheel_diameter_apply_edge_hold(
        area_name,
        center_x,
        center_y,
        axis_angle,
        moved and feedback_accepted,
        target_signed_radius,
        final_signed_radius,
        final_x,
        final_y,
        max_radius,
        debug_slow_fn,
    )
    final_signed_radius = edge_hold['final_signed_radius']
    final_x = edge_hold['final_x']
    final_y = edge_hold['final_y']

    center_final = wheel_diameter_apply_center_finalization(
        area_name,
        center_x,
        center_y,
        axis_angle,
        center_crossing,
        feedback_accepted,
        feedback_signed_radius,
        feedback_action,
        moved,
        drag,
        signed_radius,
        target_signed_radius,
        final_signed_radius,
        final_x,
        final_y,
        target_x,
        target_y,
        debug_slow_fn,
    )
    final_signed_radius = center_final['final_signed_radius']
    final_x = center_final['final_x']
    final_y = center_final['final_y']
    center_cross_visual_commit = center_final['center_cross_visual_commit']
    center_cross_unconfirmed = center_final['center_cross_unconfirmed']

    final_commit = wheel_diameter_final_commit_context(
        center_x,
        center_y,
        axis_angle,
        final_signed_radius,
        outer_control_radius,
        center_cross_visual_commit,
        center_cross_unconfirmed,
        feedback_accepted,
        moved,
    )
    return {
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
        'state_angle': final_commit['state_angle'],
        'final_outer_x': final_commit['final_outer_x'],
        'final_outer_y': final_commit['final_outer_y'],
        'final_control_angle': final_commit['final_control_angle'],
        'center_cross_unconfirmed': final_commit['center_cross_unconfirmed'],
        'feedback_confirmed': final_commit['feedback_confirmed'],
        'feedback_unconfirmed': final_commit['feedback_unconfirmed'],
        'needs_fresh_handle': final_commit['needs_fresh_handle'],
        'state_source': final_commit['state_source'],
    }


__all__ = ['wheel_diameter_finalize_after_feedback']
