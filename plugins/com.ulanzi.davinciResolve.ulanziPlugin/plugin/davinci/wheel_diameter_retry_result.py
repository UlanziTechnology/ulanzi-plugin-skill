"""Result payload helpers for wheel diameter retry handling."""


def wheel_diameter_retry_result(
    moved,
    final_signed_radius,
    final_x,
    final_y,
    cursor_end_x,
    cursor_end_y,
    last_detected_handle,
    wrong_side_feedback_ignored,
    outer_control_failed,
    feedback_accepted,
    feedback_signed_radius=None,
    feedback_action=None,
):
    return {
        'moved': moved,
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'cursor_end_x': cursor_end_x,
        'cursor_end_y': cursor_end_y,
        'last_detected_handle': last_detected_handle,
        'wrong_side_feedback_ignored': wrong_side_feedback_ignored,
        'outer_control_failed': outer_control_failed,
        'feedback_accepted': feedback_accepted,
        'feedback_signed_radius': feedback_signed_radius,
        'feedback_action': feedback_action,
    }


def wheel_diameter_retry_result_from_execution(current_result, retry_execution):
    if not retry_execution['attempted']:
        return current_result

    retry_update = retry_execution['feedback_update']
    last_detected_handle = current_result['last_detected_handle']
    if retry_execution['last_detected_handle']:
        last_detected_handle = retry_execution['last_detected_handle']

    return wheel_diameter_retry_result(
        retry_execution['retry_moved'] or current_result['moved'],
        retry_update['final_signed_radius'],
        retry_update['final_x'],
        retry_update['final_y'],
        retry_execution['cursor_end_x'],
        retry_execution['cursor_end_y'],
        last_detected_handle,
        retry_update['wrong_side_feedback_ignored'],
        retry_update['outer_control_failed'],
        retry_update['feedback_accepted'],
        retry_update.get('feedback_signed_radius', current_result.get('feedback_signed_radius')),
        retry_update.get('feedback_action', current_result.get('feedback_action')),
    )


__all__ = [
    'wheel_diameter_retry_result',
    'wheel_diameter_retry_result_from_execution',
]
