"""Feedback projection and retry decisions for diameter push/pull gestures."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_PX,
    WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_RATIO,
    WHEEL_DIAMETER_CENTER_FEEDBACK_COMMIT_RADIUS,
    WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS,
    WHEEL_DIAMETER_CENTER_FORCE_CROSS_RADIUS,
    WHEEL_DIAMETER_FEEDBACK_AXIS_TOLERANCE_PX,
    WHEEL_DIAMETER_FEEDBACK_CENTER_REJECT_RADIUS,
    WHEEL_DIAMETER_FEEDBACK_WRONG_SIGN_RADIUS,
    WHEEL_DIAMETER_RETRY_MIN_DELTA,
    WHEEL_DIAMETER_RETRY_PROGRESS_PX,
    WHEEL_HANDLE_CENTER_IGNORE_RADIUS,
)
from .wheel_diameter_geometry import wheel_diameter_point


def wheel_diameter_feedback_axis_tolerance(max_radius, target_signed_radius, feedback_signed_radius, center_crossing):
    base_tolerance = max(
        WHEEL_DIAMETER_FEEDBACK_AXIS_TOLERANCE_PX,
        min(18.0, max_radius * 0.22),
    )
    if not center_crossing:
        return base_tolerance

    feedback_on_target_side = target_signed_radius * feedback_signed_radius > 0
    if (
        not feedback_on_target_side
        or abs(feedback_signed_radius) < WHEEL_DIAMETER_CENTER_FEEDBACK_COMMIT_RADIUS
    ):
        return base_tolerance

    center_tolerance = min(
        WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_PX,
        max_radius * WHEEL_DIAMETER_CENTER_FEEDBACK_AXIS_TOLERANCE_RATIO,
    )
    return max(base_tolerance, center_tolerance)


def wheel_diameter_feedback_decision(target_signed_radius, feedback_signed_radius, crossing):
    wrong_side = target_signed_radius * feedback_signed_radius < 0

    if (
        crossing
        and wrong_side
        and abs(feedback_signed_radius) >= WHEEL_DIAMETER_CENTER_FEEDBACK_COMMIT_RADIUS
    ):
        return 'ignore-cross-wrong-side'

    target_near_center = (
        abs(target_signed_radius)
        <= WHEEL_DIAMETER_CENTER_FORCE_CROSS_RADIUS
    )
    feedback_far_from_center = (
        abs(feedback_signed_radius)
        >= WHEEL_DIAMETER_FEEDBACK_CENTER_REJECT_RADIUS
    )
    if target_near_center and feedback_far_from_center:
        feedback_on_target_side = target_signed_radius * feedback_signed_radius > 0
        if crossing and feedback_on_target_side:
            return 'accept'
        return 'ignore-center-far'

    target_far_enough = abs(target_signed_radius) >= WHEEL_DIAMETER_FEEDBACK_WRONG_SIGN_RADIUS
    feedback_far_enough = abs(feedback_signed_radius) >= WHEEL_DIAMETER_FEEDBACK_WRONG_SIGN_RADIUS
    if target_far_enough and feedback_far_enough and wrong_side:
        return 'resync-cross' if crossing else 'ignore-wrong-side'

    return 'accept'


def wheel_diameter_feedback_context(
    feedback,
    center_x,
    center_y,
    axis_angle,
    max_radius,
    target_signed_radius,
    center_crossing,
    decision_crossing=None,
):
    if not feedback:
        return None

    feedback_dx = feedback['x'] - center_x
    feedback_dy = feedback['y'] - center_y
    feedback_distance = math.hypot(feedback_dx, feedback_dy)
    feedback_ignore_radius = (
        WHEEL_DIAMETER_CENTER_FEEDBACK_IGNORE_RADIUS
        if center_crossing
        else WHEEL_HANDLE_CENTER_IGNORE_RADIUS
    )
    if feedback_distance < feedback_ignore_radius:
        return {
            'projected': False,
            'reason': 'near-center',
            'feedback_distance': feedback_distance,
            'feedback_ignore_radius': feedback_ignore_radius,
        }

    feedback_cross_radius = abs(
        -feedback_dx * math.sin(axis_angle)
        + feedback_dy * math.cos(axis_angle)
    )
    feedback_signed_radius = (
        feedback_dx * math.cos(axis_angle)
        + feedback_dy * math.sin(axis_angle)
    )
    feedback_signed_radius = max(
        -max_radius,
        min(max_radius, feedback_signed_radius),
    )
    feedback_axis_tolerance = wheel_diameter_feedback_axis_tolerance(
        max_radius,
        target_signed_radius,
        feedback_signed_radius,
        center_crossing,
    )
    if feedback_cross_radius > feedback_axis_tolerance:
        return {
            'projected': False,
            'reason': 'off-axis',
            'feedback_cross_radius': feedback_cross_radius,
            'feedback_axis_tolerance': feedback_axis_tolerance,
        }

    feedback_x, feedback_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        feedback_signed_radius,
    )
    if decision_crossing is None:
        decision_crossing = center_crossing
    action = wheel_diameter_feedback_decision(
        target_signed_radius,
        feedback_signed_radius,
        decision_crossing,
    )
    result = (feedback_signed_radius, feedback_x, feedback_y)
    return {
        'projected': True,
        'action': action,
        'feedback_signed_radius': feedback_signed_radius,
        'feedback_x': feedback_x,
        'feedback_y': feedback_y,
        'result': result,
    }


def wheel_diameter_feedback_update(
    feedback_context,
    final_signed_radius,
    final_x,
    final_y,
    feedback_handle=None,
    outer_control_crossing=False,
    wrong_side_feedback_ignored=False,
    outer_control_failed=False,
    feedback_accepted=False,
):
    result = {
        'log_action': None,
        'feedback_action': None,
        'feedback_signed_radius': None,
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
        'feedback_handle': feedback_handle,
        'wrong_side_feedback_ignored': wrong_side_feedback_ignored,
        'outer_control_failed': outer_control_failed,
        'feedback_accepted': feedback_accepted,
    }
    if not feedback_context or not feedback_context.get('projected'):
        result['feedback_handle'] = None
        return result

    feedback_result = feedback_context['result']
    feedback_signed_radius, feedback_x, feedback_y = feedback_result
    feedback_action = feedback_context['action']
    result.update({
        'feedback_action': feedback_action,
        'feedback_signed_radius': feedback_signed_radius,
    })

    if feedback_action == 'accept':
        result.update({
            'log_action': 'accept',
            'final_signed_radius': feedback_signed_radius,
            'final_x': feedback_x,
            'final_y': feedback_y,
            'feedback_accepted': True,
        })
    elif feedback_action == 'resync-cross':
        result.update({
            'log_action': 'resync-cross',
            'final_signed_radius': feedback_signed_radius,
            'final_x': feedback_x,
            'final_y': feedback_y,
            'feedback_handle': None,
            'wrong_side_feedback_ignored': True,
            'outer_control_failed': bool(outer_control_failed or outer_control_crossing),
            'feedback_accepted': True,
        })
    else:
        result.update({
            'log_action': 'ignored',
            'feedback_handle': None,
            'wrong_side_feedback_ignored': True,
        })
    return result


def wheel_diameter_retry_needed(
    moved,
    feedback_handle,
    outer_control_failed,
    wrong_side_feedback_ignored,
    signed_radius,
    target_signed_radius,
    final_signed_radius,
):
    requested_delta = target_signed_radius - signed_radius
    feedback_delta = final_signed_radius - signed_radius
    needed = (
        moved
        and feedback_handle
        and not outer_control_failed
        and (
            wrong_side_feedback_ignored
            or (
                abs(requested_delta) >= WHEEL_DIAMETER_RETRY_MIN_DELTA
                and abs(feedback_delta) <= WHEEL_DIAMETER_RETRY_PROGRESS_PX
            )
        )
    )
    return {
        'needed': bool(needed),
        'requested_delta': requested_delta,
        'feedback_delta': feedback_delta,
    }


__all__ = [
    'wheel_diameter_feedback_axis_tolerance',
    'wheel_diameter_feedback_context',
    'wheel_diameter_feedback_decision',
    'wheel_diameter_feedback_update',
    'wheel_diameter_retry_needed',
]
