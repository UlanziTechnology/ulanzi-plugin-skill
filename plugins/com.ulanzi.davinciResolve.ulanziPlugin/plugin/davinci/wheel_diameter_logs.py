"""Log message builders for diameter push/pull gestures."""

import math


def wheel_diameter_adjust_log_message(
    area_name,
    drag_source,
    drag_mode,
    signed_radius,
    target_signed_radius,
    max_radius,
    axis_angle,
    target_control_angle,
    center_crossing,
    input_dx,
    input_dy,
    mouse_input_dx,
    mouse_input_dy,
    target_outer_x,
    target_outer_y,
    logical_start_x,
    logical_start_y,
    safe_press_used,
    axis_lock_source,
    cursor_start_x,
    cursor_start_y,
    press_x,
    press_y,
):
    return (
        f"adjust {area_name}: diameter {drag_source} mode={drag_mode} actual={signed_radius:.1f} "
        f"target={target_signed_radius:.1f} "
        f"max={max_radius:.1f} "
        f"axis={math.degrees(axis_angle):.1f} "
        f"control={math.degrees(target_control_angle):.1f} "
        f"cross={center_crossing} "
        f"input=({input_dx:.0f}, {input_dy:.0f}) "
        f"mouse=({mouse_input_dx:.0f}, {mouse_input_dy:.0f}) "
        f"outer=({target_outer_x:.0f}, {target_outer_y:.0f}) "
        f"logical=({logical_start_x:.0f}, {logical_start_y:.0f}) "
        f"safe={int(bool(safe_press_used))} "
        f"lock={axis_lock_source or '-'} "
        f"from=({cursor_start_x:.0f}, {cursor_start_y:.0f}) "
        f"press=({press_x:.0f}, {press_y:.0f})"
    )


def wheel_diameter_off_axis_log_message(area_name, feedback_context):
    if not feedback_context or feedback_context.get('reason') != 'off-axis':
        return None
    return (
        f"diameter feedback off-axis {area_name} "
        f"cross={feedback_context['feedback_cross_radius']:.1f} "
        f"limit={feedback_context['feedback_axis_tolerance']:.1f}"
    )


def wheel_diameter_feedback_log_message(
    area_name,
    feedback_update,
    target_signed_radius,
    *,
    retry=False,
):
    log_action = feedback_update.get('log_action')
    if log_action == 'accept':
        actual_label = 'retry_actual' if retry else 'actual'
        return (
            'print',
            f"feedback {area_name}: diameter {actual_label}={feedback_update['final_signed_radius']:.1f} "
            f"target={target_signed_radius:.1f}",
        )

    feedback_signed_radius = feedback_update.get('feedback_signed_radius')
    if log_action == 'resync-cross':
        prefix = 'diameter retry feedback resync' if retry else 'diameter feedback resync'
        return (
            'debug',
            f"{prefix} {area_name} "
            f"actual={feedback_signed_radius:.1f} target={target_signed_radius:.1f}",
        )

    if log_action == 'ignored':
        prefix = 'diameter retry feedback ignored' if retry else 'diameter feedback ignored'
        return (
            'debug',
            f"{prefix} {area_name} "
            f"reason={feedback_update.get('feedback_action')} actual={feedback_signed_radius:.1f} "
            f"target={target_signed_radius:.1f}",
        )

    return None, None


def wheel_diameter_retry_log_message(
    area_name,
    retry_mode,
    final_signed_radius,
    target_signed_radius,
    retry_crossing,
    retry_dx,
    retry_dy,
    retry_mouse_dx,
    retry_mouse_dy,
    retry_logical_start_x,
    retry_logical_start_y,
    retry_safe_press_used,
    retry_press_x,
    retry_press_y,
    retry_start_x,
    retry_start_y,
):
    return (
        f"retry {area_name}: diameter {retry_mode} actual={final_signed_radius:.1f} "
        f"target={target_signed_radius:.1f} "
        f"cross={retry_crossing} "
        f"input=({retry_dx:.0f}, {retry_dy:.0f}) "
        f"mouse=({retry_mouse_dx:.0f}, {retry_mouse_dy:.0f}) "
        f"logical=({retry_logical_start_x:.0f}, {retry_logical_start_y:.0f}) "
        f"safe={int(retry_safe_press_used)} "
        f"from=({retry_press_x:.0f}, {retry_press_y:.0f}) "
        f"handle=({retry_start_x:.0f}, {retry_start_y:.0f})"
    )


def wheel_diameter_learn_outer_log_message(
    area_name,
    final_signed_radius,
    target_signed_radius,
    effective_max_radius,
):
    return (
        f"diameter learned outer limit {area_name} "
        f"actual={final_signed_radius:.1f} target={target_signed_radius:.1f} "
        f"max={effective_max_radius:.1f}"
    )


def wheel_diameter_edge_hold_log_message(
    area_name,
    previous_final_signed_radius,
    target_signed_radius,
    max_radius,
):
    return (
        f"diameter edge hold {area_name} "
        f"actual={previous_final_signed_radius:.1f} "
        f"target={target_signed_radius:.1f} max={max_radius:.1f}"
    )


def wheel_diameter_center_final_log_message(
    area_name,
    action,
    signed_radius,
    target_signed_radius,
    axis_lock_source=None,
):
    if action == 'visual_commit':
        return (
            f"diameter center-cross visual-commit {area_name} "
            f"actual={signed_radius:.1f} target={target_signed_radius:.1f} "
            f"lock={axis_lock_source or '-'}"
        )
    if action == 'hold':
        return (
            f"diameter center-cross hold {area_name} "
            f"actual={signed_radius:.1f} target={target_signed_radius:.1f}"
        )
    return None


__all__ = [
    'wheel_diameter_adjust_log_message',
    'wheel_diameter_center_final_log_message',
    'wheel_diameter_edge_hold_log_message',
    'wheel_diameter_feedback_log_message',
    'wheel_diameter_learn_outer_log_message',
    'wheel_diameter_off_axis_log_message',
    'wheel_diameter_retry_log_message',
]
