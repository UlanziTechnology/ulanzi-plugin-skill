"""Outer-limit learning for wheel diameter gestures."""

from .wheel_diameter_final_logic import wheel_diameter_learn_outer_limit
from .wheel_diameter_logs import wheel_diameter_learn_outer_log_message


def wheel_diameter_apply_outer_limit_learning(
    area,
    area_name,
    center_x,
    center_y,
    wheel_radius,
    visual_radius,
    outer_control_radius,
    moved,
    signed_radius,
    target_signed_radius,
    final_signed_radius,
    max_radius,
    effective_max_radius,
    last_detected_handle,
    commit_wheel_capability_to_store_fn,
    debug_slow_fn=None,
):
    learn_plan = wheel_diameter_learn_outer_limit(
        moved,
        signed_radius,
        target_signed_radius,
        final_signed_radius,
        max_radius,
        effective_max_radius,
    )
    if not learn_plan['should_learn']:
        return {
            'max_radius': max_radius,
            'effective_max_radius': effective_max_radius,
        }

    effective_max_radius = learn_plan['effective_max_radius']
    max_radius = learn_plan['max_radius']
    if debug_slow_fn:
        debug_slow_fn(wheel_diameter_learn_outer_log_message(
            area_name,
            final_signed_radius,
            target_signed_radius,
            effective_max_radius,
        ))
    commit_wheel_capability_to_store_fn(
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
        visual_radius=visual_radius,
        effective_max_radius=effective_max_radius,
        outer_control_radius=outer_control_radius,
        last_detected_handle=last_detected_handle,
        source='diameter_learn_outer',
    )
    return {
        'max_radius': max_radius,
        'effective_max_radius': effective_max_radius,
    }


__all__ = ['wheel_diameter_apply_outer_limit_learning']
