"""Retry and final-state commit for a wheel diameter session."""

from ..wheel_diameter_final_commit_context import wheel_diameter_commit_final_result
from ..wheel_diameter_finalization import wheel_diameter_finalize_after_feedback
from .retry import retry_diameter_session


def finish_diameter_session(
    area,
    preparation,
    active_context,
    target_context,
    feedback_context,
    runtime,
):
    retry_result = retry_diameter_session(
        area,
        preparation,
        active_context,
        target_context,
        feedback_context,
        runtime,
    )

    final_context = wheel_diameter_finalize_after_feedback(
        area,
        preparation.area_name,
        active_context['center_x'],
        active_context['center_y'],
        active_context['wheel_radius'],
        active_context['visual_radius'],
        active_context['outer_control_radius'],
        active_context['axis_angle'],
        active_context['signed_radius'],
        target_context['target_signed_radius'],
        retry_result['final_signed_radius'],
        retry_result['final_x'],
        retry_result['final_y'],
        active_context['max_radius'],
        active_context['effective_max_radius'],
        retry_result['moved'],
        retry_result['feedback_accepted'],
        retry_result.get('feedback_signed_radius'),
        retry_result.get('feedback_action'),
        target_context['center_crossing'],
        active_context['drag'],
        target_context['target_x'],
        target_context['target_y'],
        retry_result['last_detected_handle'],
        runtime.state.commit_wheel_capability_to_store,
        runtime.debug_slow,
    )
    wheel_diameter_commit_final_result(
        area,
        preparation.area_name,
        preparation.target_key,
        active_context['center_x'],
        active_context['center_y'],
        active_context['wheel_radius'],
        active_context['visual_radius'],
        active_context['outer_control_radius'],
        active_context['axis_angle'],
        final_context,
        retry_result['cursor_end_x'],
        retry_result['cursor_end_y'],
        retry_result['last_detected_handle'],
        active_context['drag'],
        runtime.release_wheel_drag,
        runtime.state.commit_wheel_diameter_state,
        runtime.state.set_wheel_diameter_axis_lock,
    )
    return retry_result['moved']


__all__ = ['finish_diameter_session']
