"""Mouse execution and visual feedback for diameter gestures."""

from ..config import (
    WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_PX,
    WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_RATIO,
    WHEEL_DIAMETER_FEEDBACK_AXIS_TOLERANCE_PX,
)
from ..wheel_diameter_feedback_detection import wheel_diameter_detect_feedback_handle
from ..wheel_diameter_geometry import wheel_diameter_point
from ..wheel_diameter_feedback_logic import (
    wheel_diameter_feedback_context,
    wheel_diameter_feedback_update,
)
from ..wheel_diameter_logs import (
    wheel_diameter_feedback_log_message,
    wheel_diameter_off_axis_log_message,
)
from ..wheel_diameter_mouse_execution import wheel_diameter_execute_mouse_path


def _axis_tolerance(max_radius, center_crossing):
    base_tolerance = max(
        WHEEL_DIAMETER_FEEDBACK_AXIS_TOLERANCE_PX,
        min(18.0, max_radius * 0.22),
    )
    if not center_crossing:
        return base_tolerance
    center_tolerance = min(
        WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_PX,
        max_radius * WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_RATIO,
    )
    return max(base_tolerance, center_tolerance)


def _detect_feedback(
    area,
    area_name,
    center_x,
    center_y,
    axis_angle,
    max_radius,
    target_signed_radius,
    target_x,
    target_y,
    center_crossing,
    detect_raw_handle,
    *,
    decision_crossing=None,
    settle_crossing=None,
    debug_slow=None,
):
    expected_axis = {
        'axis_angle': axis_angle,
        'axis_tolerance': _axis_tolerance(max_radius, center_crossing),
    }
    expected_handle = None
    if center_crossing:
        expected_handle = {
            'x': target_x,
            'y': target_y,
            'allow_center_candidate': True,
        }
    detected_handle = wheel_diameter_detect_feedback_handle(
        area,
        center_crossing,
        settle_crossing,
        detect_raw_handle,
        expected_handle=expected_handle,
        expected_axis=expected_axis,
    )
    if not detected_handle and debug_slow:
        debug_slow(
            f"diameter feedback no axis candidate {area_name} "
            f"limit={expected_axis['axis_tolerance']:.1f}"
        )
    feedback_context = wheel_diameter_feedback_context(
        detected_handle,
        center_x,
        center_y,
        axis_angle,
        max_radius,
        target_signed_radius,
        center_crossing,
        decision_crossing=decision_crossing,
    )
    off_axis_message = wheel_diameter_off_axis_log_message(
        area_name,
        feedback_context,
    )
    if off_axis_message and debug_slow:
        debug_slow(off_axis_message)
    return detected_handle, feedback_context


def _apply_feedback_update(
    area_name,
    feedback_context,
    detected_handle,
    final_signed_radius,
    final_x,
    final_y,
    target_signed_radius,
    *,
    feedback_handle_for_update=True,
    outer_control_crossing=False,
    wrong_side_feedback_ignored=False,
    outer_control_failed=False,
    feedback_accepted=False,
    retry=False,
    debug_slow=None,
):
    feedback_update = wheel_diameter_feedback_update(
        feedback_context,
        final_signed_radius,
        final_x,
        final_y,
        feedback_handle=detected_handle if feedback_handle_for_update else None,
        outer_control_crossing=outer_control_crossing,
        wrong_side_feedback_ignored=wrong_side_feedback_ignored,
        outer_control_failed=outer_control_failed,
        feedback_accepted=feedback_accepted,
    )
    log_kind, log_message = wheel_diameter_feedback_log_message(
        area_name,
        feedback_update,
        target_signed_radius,
        retry=retry,
    )
    if log_kind == 'print':
        print(log_message)
    elif log_kind == 'debug' and debug_slow:
        debug_slow(log_message)
    return feedback_update


def diameter_feedback_result(
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
    detect_raw_handle,
    *,
    decision_crossing=None,
    settle_crossing=None,
    feedback_handle_for_update=True,
    outer_control_crossing=False,
    wrong_side_feedback_ignored=False,
    outer_control_failed=False,
    feedback_accepted=False,
    retry=False,
    debug_slow=None,
):
    detected_handle, feedback_context = _detect_feedback(
        area,
        area_name,
        center_x,
        center_y,
        axis_angle,
        max_radius,
        target_signed_radius,
        final_x,
        final_y,
        center_crossing,
        detect_raw_handle,
        decision_crossing=decision_crossing,
        settle_crossing=settle_crossing,
        debug_slow=debug_slow,
    )
    feedback_update = _apply_feedback_update(
        area_name,
        feedback_context,
        detected_handle,
        final_signed_radius,
        final_x,
        final_y,
        target_signed_radius,
        feedback_handle_for_update=feedback_handle_for_update,
        outer_control_crossing=outer_control_crossing,
        wrong_side_feedback_ignored=wrong_side_feedback_ignored,
        outer_control_failed=outer_control_failed,
        feedback_accepted=feedback_accepted,
        retry=retry,
        debug_slow=debug_slow,
    )
    return {
        'feedback_update': feedback_update,
        'last_detected_handle': detected_handle,
        'feedback_context': feedback_context,
    }


def _after_mouse_feedback(
    area,
    preparation,
    active_context,
    target_context,
    mouse_result,
    runtime,
):
    final_signed_radius = active_context.get(
        'confirmed_signed_radius',
        active_context['signed_radius'],
    )
    final_x, final_y = wheel_diameter_point(
        active_context['center_x'],
        active_context['center_y'],
        active_context['axis_angle'],
        final_signed_radius,
    )
    if not mouse_result['ok']:
        cursor_x, cursor_y = runtime.get_cursor_position()
        if runtime.debug_slow:
            runtime.debug_slow(
                f"diameter feedback unconfirmed {preparation.area_name} "
                f"reason=mouse-execution-failed keep={final_signed_radius:.1f} "
                f"target={target_context['target_signed_radius']:.1f}"
            )
        return {
            'ok': True,
            'moved': False,
            'cursor_start_x': cursor_x,
            'cursor_start_y': cursor_y,
            'cursor_end_x': cursor_x,
            'cursor_end_y': cursor_y,
            'final_signed_radius': final_signed_radius,
            'final_x': final_x,
            'final_y': final_y,
            'feedback_handle': None,
            'last_detected_handle': None,
            'wrong_side_feedback_ignored': False,
            'outer_control_failed': False,
            'feedback_accepted': False,
            'feedback_signed_radius': None,
            'feedback_action': None,
            'feedback_reason': 'mouse-execution-failed',
        }

    moved = mouse_result['moved']
    feedback_handle = None
    last_detected_handle = None
    feedback_detection_context = None
    wrong_side_feedback_ignored = False
    outer_control_failed = False
    feedback_accepted = False
    feedback_signed_radius = None
    feedback_action = None

    if moved:
        feedback_result = diameter_feedback_result(
            area,
            preparation.area_name,
            active_context['center_x'],
            active_context['center_y'],
            active_context['axis_angle'],
            active_context['max_radius'],
            target_context['target_signed_radius'],
            target_context['center_crossing'],
            final_signed_radius,
            final_x,
            final_y,
            runtime.detect_raw_handle,
            outer_control_crossing=target_context['outer_control_crossing'],
            wrong_side_feedback_ignored=wrong_side_feedback_ignored,
            outer_control_failed=outer_control_failed,
            feedback_accepted=feedback_accepted,
            debug_slow=runtime.debug_slow,
        )
        feedback_update = feedback_result['feedback_update']
        last_detected_handle = feedback_result['last_detected_handle']
        feedback_detection_context = feedback_result['feedback_context']
        final_signed_radius = feedback_update['final_signed_radius']
        final_x = feedback_update['final_x']
        final_y = feedback_update['final_y']
        feedback_handle = feedback_update['feedback_handle']
        wrong_side_feedback_ignored = feedback_update['wrong_side_feedback_ignored']
        outer_control_failed = feedback_update['outer_control_failed']
        feedback_accepted = feedback_update['feedback_accepted']
        feedback_signed_radius = feedback_update['feedback_signed_radius']
        feedback_action = feedback_update['feedback_action']

    feedback_reason = None
    if not feedback_accepted:
        if not moved:
            feedback_reason = 'mouse-not-moved'
        elif not feedback_detection_context:
            feedback_reason = 'no-handle'
        elif not feedback_detection_context.get('projected'):
            feedback_reason = feedback_detection_context.get('reason', 'not-projected')
        else:
            feedback_reason = feedback_action or 'not-accepted'
        if runtime.debug_slow:
            runtime.debug_slow(
                f"diameter feedback unconfirmed {preparation.area_name} "
                f"reason={feedback_reason} keep={final_signed_radius:.1f} "
                f"target={target_context['target_signed_radius']:.1f}"
            )

    return {
        'ok': True,
        'moved': moved,
        'cursor_start_x': mouse_result['cursor_start_x'],
        'cursor_start_y': mouse_result['cursor_start_y'],
        'cursor_end_x': mouse_result['cursor_end_x'],
        'cursor_end_y': mouse_result['cursor_end_y'],
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'feedback_handle': feedback_handle,
        'last_detected_handle': last_detected_handle,
        'wrong_side_feedback_ignored': wrong_side_feedback_ignored,
        'outer_control_failed': outer_control_failed,
        'feedback_accepted': feedback_accepted,
        'feedback_signed_radius': feedback_signed_radius,
        'feedback_action': feedback_action,
        'feedback_reason': feedback_reason,
    }


def execute_diameter_target(
    area,
    preparation,
    active_context,
    target_context,
    runtime,
):
    mouse_result = wheel_diameter_execute_mouse_path(
        preparation.area_name,
        active_context['drag'],
        active_context['drag_source'],
        active_context['signed_radius'],
        target_context['target_signed_radius'],
        active_context['max_radius'],
        active_context['axis_angle'],
        target_context['target_control_angle'],
        target_context['center_crossing'],
        target_context['target_x'],
        target_context['target_y'],
        target_context['target_outer_x'],
        target_context['target_outer_y'],
        active_context['start_reference_x'],
        active_context['start_reference_y'],
        target_context['mouse_plan'],
        target_context['cursor_start_x'],
        target_context['cursor_start_y'],
        target_context['logical_start_x'],
        target_context['logical_start_y'],
        runtime.mouse_drag_begin,
        runtime.mouse_drag_move_absolute_path,
        runtime.mouse_drag_end,
        runtime.get_cursor_position,
        runtime.release_wheel_drag,
        runtime.state.clear_wheel_drag_state,
    )
    return _after_mouse_feedback(
        area,
        preparation,
        active_context,
        target_context,
        mouse_result,
        runtime,
    )


__all__ = ['diameter_feedback_result', 'execute_diameter_target']
