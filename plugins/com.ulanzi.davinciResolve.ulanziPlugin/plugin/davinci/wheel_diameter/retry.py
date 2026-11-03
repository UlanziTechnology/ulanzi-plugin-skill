"""Optional corrective pass after diameter mouse feedback."""

from ..wheel_diameter_feedback_logic import wheel_diameter_retry_needed
from ..wheel_diameter_retry_execution import wheel_diameter_execute_retry_plan
from ..wheel_diameter_retry_logic import wheel_diameter_retry_plan
from ..wheel_diameter_retry_result import (
    wheel_diameter_retry_result,
    wheel_diameter_retry_result_from_execution,
)


def retry_diameter_session(
    area,
    preparation,
    active_context,
    target_context,
    feedback_context,
    runtime,
):
    retry_needed = wheel_diameter_retry_needed(
        feedback_context['moved'],
        feedback_context['feedback_handle'],
        feedback_context['outer_control_failed'],
        feedback_context['wrong_side_feedback_ignored'],
        active_context['signed_radius'],
        target_context['target_signed_radius'],
        feedback_context['final_signed_radius'],
    )
    current_result = wheel_diameter_retry_result(
        feedback_context['moved'],
        feedback_context['final_signed_radius'],
        feedback_context['final_x'],
        feedback_context['final_y'],
        feedback_context['cursor_end_x'],
        feedback_context['cursor_end_y'],
        feedback_context['last_detected_handle'],
        feedback_context['wrong_side_feedback_ignored'],
        feedback_context['outer_control_failed'],
        feedback_context['feedback_accepted'],
        feedback_context.get('feedback_signed_radius'),
        feedback_context.get('feedback_action'),
    )
    if not retry_needed['needed']:
        return current_result

    drag = active_context['drag']
    retry_handle = feedback_context['feedback_handle'] or active_context['handle']
    if drag is None or drag.get('button_down', True):
        runtime.mouse_drag_end(
            feedback_context['cursor_end_x'],
            feedback_context['cursor_end_y'],
            pre_delay=0.0,
            post_delay=0.02,
        )
    if drag is not None:
        drag['button_down'] = False

    retry_plan = wheel_diameter_retry_plan(
        retry_handle,
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        target_context['target_signed_radius'],
        target_context['target_x'],
        target_context['target_y'],
        active_context['max_radius'],
    )
    if retry_plan['retry_safe_origin_inward'] and runtime.debug_slow:
        runtime.debug_slow(
            f"diameter retry safe origin {preparation.area_name} "
            f"actual={retry_plan['retry_initial_signed_radius']:.1f} "
            f"start={retry_plan['retry_safe_signed_radius']:.1f} "
            f"target={target_context['target_signed_radius']:.1f}"
        )
    retry_execution = wheel_diameter_execute_retry_plan(
        area,
        preparation.area_name,
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        active_context['max_radius'],
        target_context['target_signed_radius'],
        target_context['center_crossing'],
        feedback_context['final_signed_radius'],
        feedback_context['final_x'],
        feedback_context['final_y'],
        retry_plan,
        feedback_context['wrong_side_feedback_ignored'],
        feedback_context['outer_control_failed'],
        feedback_context['feedback_accepted'],
        runtime.mouse_drag_begin,
        runtime.mouse_drag_move_absolute_path,
        runtime.mouse_drag_end,
        runtime.get_cursor_position,
        runtime.detect_raw_handle,
        runtime.release_wheel_drag,
        drag=drag,
        debug_slow_fn=runtime.debug_slow,
    )
    return wheel_diameter_retry_result_from_execution(
        current_result,
        retry_execution,
    )


__all__ = ['retry_diameter_session']
