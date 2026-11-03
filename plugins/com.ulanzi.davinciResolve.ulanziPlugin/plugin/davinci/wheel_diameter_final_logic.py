"""Final radius, edge hold, and commit planning for diameter gestures."""

import math

from .config import (
    WHEEL_DIAMETER_CENTER_CROSS_EPSILON,
    WHEEL_DIAMETER_CENTER_MAJORITY_COMMIT_RADIUS,
    WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_ENABLED,
    WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_RADIUS,
    WHEEL_DIAMETER_EDGE_HOLD_EPSILON,
    WHEEL_DIAMETER_EDGE_LOCK_EPSILON,
    WHEEL_DIAMETER_LEARN_OUTER_LIMIT_EDGE_MARGIN_PX,
    WHEEL_DIAMETER_LEARN_OUTER_LIMIT_EDGE_RATIO,
    WHEEL_DIAMETER_LEARN_OUTER_LIMIT_MIN_RADIUS,
    WHEEL_DIAMETER_LEARN_OUTER_LIMIT_PROGRESS_PX,
    WHEEL_DIAMETER_LEARN_OUTER_LIMIT_SOFT_RATIO,
    WHEEL_DIAMETER_RETRY_MIN_DELTA,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_diameter_geometry import (
    wheel_diameter_display_angle,
    wheel_diameter_outer_control_point,
    wheel_diameter_point,
)


def wheel_diameter_learn_outer_limit(
    moved,
    signed_radius,
    target_signed_radius,
    final_signed_radius,
    max_radius,
    effective_max_radius,
):
    outward_requested = (
        abs(target_signed_radius) > abs(signed_radius) + WHEEL_DIAMETER_RETRY_MIN_DELTA
        and (
            abs(signed_radius) <= WHEEL_DIAMETER_CENTER_CROSS_EPSILON
            or target_signed_radius * signed_radius > 0
        )
    )
    result = {
        'outward_requested': outward_requested,
        'should_learn': False,
        'effective_max_radius': effective_max_radius,
        'max_radius': max_radius,
        'learned_max_radius': None,
        'radius_progress': None,
        'remaining_gap': None,
        'learn_outer_threshold': None,
    }
    if not moved or not outward_requested:
        return result

    radius_progress = abs(final_signed_radius) - abs(signed_radius)
    remaining_gap = abs(target_signed_radius) - abs(final_signed_radius)
    edge_learn_threshold = min(
        max_radius * WHEEL_DIAMETER_LEARN_OUTER_LIMIT_EDGE_RATIO,
        max_radius - WHEEL_DIAMETER_LEARN_OUTER_LIMIT_EDGE_MARGIN_PX,
    )
    soft_learn_threshold = max_radius * WHEEL_DIAMETER_LEARN_OUTER_LIMIT_SOFT_RATIO
    learn_outer_threshold = max(
        WHEEL_ROTATION_MIN_RADIUS,
        WHEEL_DIAMETER_LEARN_OUTER_LIMIT_MIN_RADIUS,
        min(edge_learn_threshold, soft_learn_threshold),
    )
    result.update({
        'radius_progress': radius_progress,
        'remaining_gap': remaining_gap,
        'learn_outer_threshold': learn_outer_threshold,
    })
    if not (
        0.0 <= radius_progress <= WHEEL_DIAMETER_LEARN_OUTER_LIMIT_PROGRESS_PX
        and remaining_gap >= WHEEL_DIAMETER_RETRY_MIN_DELTA
        and abs(final_signed_radius) >= WHEEL_ROTATION_MIN_RADIUS
        and abs(final_signed_radius) >= learn_outer_threshold
    ):
        return result

    learned_max_radius = max(WHEEL_ROTATION_MIN_RADIUS, abs(final_signed_radius))
    if effective_max_radius is not None and learned_max_radius >= effective_max_radius:
        return result

    result.update({
        'should_learn': True,
        'effective_max_radius': learned_max_radius,
        'max_radius': min(max_radius, learned_max_radius),
        'learned_max_radius': learned_max_radius,
    })
    return result


def wheel_diameter_edge_hold_plan(
    moved,
    target_signed_radius,
    final_signed_radius,
    max_radius,
    center_x,
    center_y,
    axis_angle,
):
    target_at_edge = abs(target_signed_radius) >= max_radius - WHEEL_DIAMETER_EDGE_LOCK_EPSILON
    edge_hold_gap = abs(target_signed_radius) - abs(final_signed_radius)
    result = {
        'held': False,
        'target_at_edge': target_at_edge,
        'edge_hold_gap': edge_hold_gap,
        'previous_final_signed_radius': final_signed_radius,
        'final_signed_radius': final_signed_radius,
        'final_x': None,
        'final_y': None,
    }
    if not (
        moved
        and target_at_edge
        and target_signed_radius * final_signed_radius > 0
        and 0.0 <= edge_hold_gap <= WHEEL_DIAMETER_EDGE_HOLD_EPSILON
    ):
        return result

    held_signed_radius = math.copysign(max_radius, target_signed_radius)
    final_x, final_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        held_signed_radius,
    )
    result.update({
        'held': True,
        'final_signed_radius': held_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
    })
    return result


def wheel_diameter_should_hold_center_cross(center_crossing, feedback_accepted):
    return center_crossing and not feedback_accepted


def wheel_diameter_feedback_confirms_center_cross(target_signed_radius, feedback_signed_radius):
    try:
        target_signed_radius = float(target_signed_radius)
        feedback_signed_radius = float(feedback_signed_radius)
    except (TypeError, ValueError):
        return False
    return (
        target_signed_radius * feedback_signed_radius > 0
        and abs(feedback_signed_radius) >= WHEEL_DIAMETER_CENTER_MAJORITY_COMMIT_RADIUS
    )


def wheel_diameter_should_commit_center_cross_visual(
    center_crossing,
    feedback_accepted,
    feedback_signed_radius,
    moved,
    axis_locked,
    target_signed_radius,
):
    return (
        WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_ENABLED
        and
        center_crossing
        and not feedback_accepted
        and moved
        and axis_locked
        and abs(target_signed_radius) >= WHEEL_DIAMETER_CENTER_VISUAL_COMMIT_RADIUS
        and wheel_diameter_feedback_confirms_center_cross(
            target_signed_radius,
            feedback_signed_radius,
        )
    )


def wheel_diameter_center_final_plan(
    center_crossing,
    feedback_accepted,
    feedback_signed_radius,
    moved,
    axis_locked,
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
):
    visual_commit = wheel_diameter_should_commit_center_cross_visual(
        center_crossing,
        feedback_accepted,
        feedback_signed_radius,
        moved,
        axis_locked,
        target_signed_radius,
    )
    if visual_commit:
        return {
            'action': 'visual_commit',
            'center_cross_visual_commit': True,
            'final_signed_radius': target_signed_radius,
            'final_x': target_x,
            'final_y': target_y,
        }

    if wheel_diameter_should_hold_center_cross(center_crossing, feedback_accepted):
        hold_x, hold_y = wheel_diameter_point(
            center_x,
            center_y,
            axis_angle,
            signed_radius,
        )
        return {
            'action': 'hold',
            'center_cross_visual_commit': False,
            'final_signed_radius': signed_radius,
            'final_x': hold_x,
            'final_y': hold_y,
        }

    return {
        'action': None,
        'center_cross_visual_commit': False,
        'final_signed_radius': final_signed_radius,
        'final_x': final_x,
        'final_y': final_y,
    }


def wheel_diameter_final_commit_context(
    center_x,
    center_y,
    axis_angle,
    final_signed_radius,
    outer_control_radius,
    center_cross_visual_commit,
    center_cross_unconfirmed,
    feedback_accepted,
    moved,
):
    state_angle = wheel_diameter_display_angle(axis_angle, final_signed_radius)
    final_outer_x, final_outer_y, final_control_angle = wheel_diameter_outer_control_point(
        center_x,
        center_y,
        axis_angle,
        final_signed_radius,
        outer_control_radius,
    )
    feedback_confirmed = bool(feedback_accepted or center_cross_visual_commit)
    center_cross_unconfirmed = bool(
        center_cross_unconfirmed and not feedback_confirmed
    )
    feedback_unconfirmed = bool(moved and not feedback_confirmed)
    needs_fresh_handle = bool(
        center_cross_unconfirmed or feedback_unconfirmed
    )
    return {
        'state_angle': state_angle,
        'final_outer_x': final_outer_x,
        'final_outer_y': final_outer_y,
        'final_control_angle': final_control_angle,
        'center_cross_unconfirmed': center_cross_unconfirmed,
        'feedback_confirmed': feedback_confirmed,
        'feedback_unconfirmed': feedback_unconfirmed,
        'needs_fresh_handle': needs_fresh_handle,
        'state_source': (
            'diameter_visual_commit'
            if center_cross_visual_commit
            else (
                'diameter_center_unconfirmed'
                if center_cross_unconfirmed
                else (
                    'diameter_feedback_unconfirmed'
                    if feedback_unconfirmed
                    else 'diameter_final'
                )
            )
        ),
    }


__all__ = [
    'wheel_diameter_center_final_plan',
    'wheel_diameter_edge_hold_plan',
    'wheel_diameter_final_commit_context',
    'wheel_diameter_learn_outer_limit',
]
