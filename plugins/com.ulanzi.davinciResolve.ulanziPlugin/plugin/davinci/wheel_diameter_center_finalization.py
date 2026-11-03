"""Center-cross finalization for wheel diameter gestures."""

from .config import WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_RADIUS
from .wheel_diameter_final_logic import wheel_diameter_center_final_plan
from .wheel_diameter_logs import wheel_diameter_center_final_log_message


def wheel_diameter_apply_center_finalization(
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
    debug_slow_fn=None,
):
    center_final = wheel_diameter_center_final_plan(
        center_crossing,
        feedback_accepted,
        feedback_signed_radius,
        moved,
        bool(drag.get('axis_lock_source')),
        target_signed_radius,
        signed_radius,
        final_signed_radius,
        final_x,
        final_y,
        target_x,
        target_y,
        center_x,
        center_y,
        axis_angle,
    )
    center_cross_visual_commit = center_final['center_cross_visual_commit']
    if center_final['action'] == 'visual_commit':
        final_signed_radius = center_final['final_signed_radius']
        final_x = center_final['final_x']
        final_y = center_final['final_y']
        if debug_slow_fn:
            debug_slow_fn(wheel_diameter_center_final_log_message(
                area_name,
                center_final['action'],
                signed_radius,
                target_signed_radius,
                drag.get('axis_lock_source'),
            ))
    elif center_final['action'] == 'hold':
        final_signed_radius = center_final['final_signed_radius']
        final_x = center_final['final_x']
        final_y = center_final['final_y']
        if debug_slow_fn:
            debug_slow_fn(wheel_diameter_center_final_log_message(
                area_name,
                center_final['action'],
                signed_radius,
                target_signed_radius,
            ))

    return {
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'center_cross_visual_commit': center_cross_visual_commit,
        'center_cross_unconfirmed': bool(
            center_crossing
            and not feedback_accepted
            and not center_cross_visual_commit
            and abs(final_signed_radius) > WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_RADIUS
        ),
    }


__all__ = ['wheel_diameter_apply_center_finalization']
