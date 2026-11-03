"""Mouse execution for a planned wheel diameter retry."""

from .wheel_diameter.feedback import diameter_feedback_result
from .wheel_diameter_logs import wheel_diameter_retry_log_message


def wheel_diameter_execute_retry_plan(
    area,
    area_name,
    center_x,
    center_y,
    axis_angle,
    max_radius,
    target_signed_radius,
    center_crossing,
    final_signed_radius,
    final_x,
    final_y,
    retry_plan,
    wrong_side_feedback_ignored,
    outer_control_failed,
    feedback_accepted,
    mouse_drag_begin_fn,
    mouse_drag_move_absolute_path_fn,
    mouse_drag_end_fn,
    get_cursor_position_fn,
    detect_handle_raw_for_area_fn,
    release_wheel_drag_fn,
    *,
    drag=None,
    debug_slow_fn=None,
):
    retry_start_x = retry_plan['retry_start_x']
    retry_start_y = retry_plan['retry_start_y']
    retry_logical_start_x = retry_plan['retry_logical_start_x']
    retry_logical_start_y = retry_plan['retry_logical_start_y']
    retry_press_x = retry_plan['retry_press_x']
    retry_press_y = retry_plan['retry_press_y']
    retry_safe_press_used = retry_plan['retry_safe_press_used']
    retry_crossing = retry_plan['retry_crossing']
    retry_dx = retry_plan['retry_dx']
    retry_dy = retry_plan['retry_dy']
    retry_mouse_dx = retry_plan['retry_mouse_dx']
    retry_mouse_dy = retry_plan['retry_mouse_dy']
    retry_duration = retry_plan['retry_duration']
    retry_mode = retry_plan['retry_mode']
    retry_path = retry_plan['retry_path']

    if not mouse_drag_begin_fn(retry_press_x, retry_press_y):
        return {'attempted': False}
    if drag is not None:
        drag['button_down'] = True

    print(wheel_diameter_retry_log_message(
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
    ))
    try:
        retry_moved = False
        retry_moved = mouse_drag_move_absolute_path_fn(
            retry_path,
            duration=retry_duration,
        )
        cursor_end_x, cursor_end_y = get_cursor_position_fn()
        mouse_drag_end_fn(cursor_end_x, cursor_end_y, pre_delay=0.0, post_delay=0.0)
        if drag is not None:
            drag['button_down'] = False
        retry_result = diameter_feedback_result(
            area,
            area_name,
            center_x,
            center_y,
            axis_angle,
            max_radius,
            target_signed_radius,
            center_crossing,
            final_signed_radius,
            final_x,
            final_y,
            detect_handle_raw_for_area_fn,
            decision_crossing=retry_crossing,
            settle_crossing=retry_crossing,
            feedback_handle_for_update=False,
            wrong_side_feedback_ignored=wrong_side_feedback_ignored,
            outer_control_failed=outer_control_failed,
            feedback_accepted=feedback_accepted,
            retry=True,
            debug_slow=debug_slow_fn,
        )
        return {
            'attempted': True,
            'retry_moved': retry_moved,
            'cursor_end_x': cursor_end_x,
            'cursor_end_y': cursor_end_y,
            'feedback_update': retry_result['feedback_update'],
            'last_detected_handle': retry_result['last_detected_handle'],
        }
    except Exception:
        if drag is not None:
            drag['button_down'] = False
        release_wheel_drag_fn()
        raise


__all__ = ['wheel_diameter_execute_retry_plan']
