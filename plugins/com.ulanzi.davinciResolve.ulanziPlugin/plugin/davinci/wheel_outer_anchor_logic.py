"""Decision helpers for outer-anchor wheel rotation gestures."""

import math

from .config import (
    WHEEL_ANCHOR_FEEDBACK_MAX_ANGLE_ERROR_DEGREES,
    WHEEL_ANCHOR_FORCE_FRESH_NO_PROGRESS_COUNT,
    WHEEL_ANCHOR_NEAR_CENTER_FEEDBACK_MAX_ANGLE_ERROR_DEGREES,
    WHEEL_ANCHOR_NEAR_CENTER_MIN_TANGENT_DISTANCE_PX,
    WHEEL_ANCHOR_NEAR_CENTER_RADIUS,
    WHEEL_ANCHOR_NEAR_CENTER_TANGENT_GAIN,
    WHEEL_ANCHOR_DRAG_SAFE_AREA_RATIO,
    WHEEL_ANCHOR_DRAG_SAFE_VISUAL_INSET_PX,
    WHEEL_ANCHOR_MIN_HANDLE_RADIUS,
    WHEEL_ANCHOR_FEEDBACK_RADIUS_OUTLIER_PX,
    WHEEL_ANCHOR_ADAPTIVE_DEFAULT_DEGREES,
    WHEEL_ANCHOR_ADAPTIVE_RADIUS_DEGREES_CONSTANT,
    WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_ENABLED,
    WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_MAX,
    WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_MIN,
    WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_DEADZONE_PX,
    WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_GAIN,
    WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_MAX_PX,
    WHEEL_ANCHOR_TOURBOX_STUCK_MAX_COUNT,
    WHEEL_ANCHOR_TOURBOX_STUCK_MIN_PROGRESS_DEGREES,
    WHEEL_ANCHOR_TOURBOX_STUCK_RADIAL_PULL_MAX_PX,
    WHEEL_ANCHOR_TOURBOX_STUCK_RADIAL_PULL_PX,
    WHEEL_ANCHOR_TOURBOX_STUCK_TANGENT_GAIN_MAX,
    WHEEL_ANCHOR_TOURBOX_STUCK_TANGENT_GAIN_STEP,
    WHEEL_ANCHOR_TOURBOX_TANGENT_PIXELS_PER_TICK,
    WHEEL_DIAMETER_CENTER_RESET_RADIUS,
    WHEEL_ROTATE_DEGREES_PER_TICK,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_common_geometry import normalize_angle_radians
from .wheel_orbit_model import build_tourbox_tangent_orbit_path, wheel_orbit_safe_radius
from .wheel_visual_radius import wheel_visual_radius


def _outer_anchor_tangent_radius_scale(handle_radius):
    if not WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_ENABLED:
        return 1.0
    try:
        handle_radius = float(handle_radius)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(handle_radius) or handle_radius <= 0.0:
        return 1.0
    scale = (
        WHEEL_ANCHOR_ADAPTIVE_DEFAULT_DEGREES
        * handle_radius
        / WHEEL_ANCHOR_ADAPTIVE_RADIUS_DEGREES_CONSTANT
    )
    return min(
        WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_MAX,
        max(WHEEL_ANCHOR_TANGENT_RADIUS_SCALE_MIN, scale),
    )


def outer_anchor_target(
    center_x,
    center_y,
    start_angle,
    handle_radius,
    ticks,
    sensitivity,
    degrees_per_tick=None,
):
    if degrees_per_tick is None:
        degrees_per_tick = WHEEL_ROTATE_DEGREES_PER_TICK
    delta_angle = math.radians(ticks * sensitivity * degrees_per_tick)
    target_angle = start_angle + delta_angle
    state_angle = normalize_angle_radians(target_angle)
    return {
        'delta_angle': delta_angle,
        'target_angle': target_angle,
        'state_angle': state_angle,
        'target_x': center_x + math.cos(target_angle) * handle_radius,
        'target_y': center_y + math.sin(target_angle) * handle_radius,
    }


def outer_anchor_drag_plan(
    start_x,
    start_y,
    start_angle,
    ticks,
    sensitivity,
    handle_radius,
    actual_radius,
    no_progress_count,
):
    effective_anchor_radius = max(handle_radius, actual_radius)
    near_center_anchor = effective_anchor_radius <= WHEEL_ANCHOR_NEAR_CENTER_RADIUS
    radial_error = max(
        0.0,
        actual_radius
        - handle_radius
        - WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_DEADZONE_PX,
    )
    if near_center_anchor:
        radial_pull_px = 0.0
        tangent_sensitivity = sensitivity * WHEEL_ANCHOR_NEAR_CENTER_TANGENT_GAIN
    else:
        radial_pull_px = min(
            WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_MAX_PX,
            radial_error * WHEEL_ANCHOR_TOURBOX_RADIAL_PULL_GAIN,
        )
        tangent_sensitivity = sensitivity
        if no_progress_count > 0:
            stuck_level = min(no_progress_count, WHEEL_ANCHOR_TOURBOX_STUCK_MAX_COUNT)
            stuck_tangent_gain = min(
                WHEEL_ANCHOR_TOURBOX_STUCK_TANGENT_GAIN_MAX,
                1.0 + WHEEL_ANCHOR_TOURBOX_STUCK_TANGENT_GAIN_STEP * stuck_level,
            )
            tangent_sensitivity *= stuck_tangent_gain
            if stuck_level >= 2:
                stuck_radial_pull_px = min(
                    WHEEL_ANCHOR_TOURBOX_STUCK_RADIAL_PULL_MAX_PX,
                    WHEEL_ANCHOR_TOURBOX_STUCK_RADIAL_PULL_PX * (stuck_level - 1),
                )
                radial_pull_px = max(radial_pull_px, stuck_radial_pull_px)

    tangent_radius_scale = _outer_anchor_tangent_radius_scale(handle_radius)
    tangent_sensitivity *= tangent_radius_scale
    if near_center_anchor:
        tick_units = abs(float(ticks or 0.0))
        if tick_units > 0.0:
            min_tangent_sensitivity = (
                WHEEL_ANCHOR_NEAR_CENTER_MIN_TANGENT_DISTANCE_PX
                / (tick_units * WHEEL_ANCHOR_TOURBOX_TANGENT_PIXELS_PER_TICK)
            )
            if abs(tangent_sensitivity) < min_tangent_sensitivity:
                sign = -1.0 if tangent_sensitivity < 0.0 else 1.0
                tangent_sensitivity = sign * min_tangent_sensitivity
    handle_path, tangent_dx, tangent_dy, tangent_distance = build_tourbox_tangent_orbit_path(
        start_x,
        start_y,
        start_angle,
        ticks,
        tangent_sensitivity,
        radial_pull_px=radial_pull_px,
    )
    return {
        'handle_path': handle_path,
        'tangent_dx': tangent_dx,
        'tangent_dy': tangent_dy,
        'tangent_distance': tangent_distance,
        'near_center_anchor': near_center_anchor,
        'radial_pull_px': radial_pull_px,
        'tangent_sensitivity': tangent_sensitivity,
        'tangent_radius_scale': tangent_radius_scale,
    }


def outer_anchor_drag_safe_radius(area, visual_radius, max_radius):
    area_safe_radius = max(
        WHEEL_ROTATION_MIN_RADIUS,
        min(area['w'], area['h']) * WHEEL_ANCHOR_DRAG_SAFE_AREA_RATIO,
    )
    if visual_radius:
        area_safe_radius = min(
            area_safe_radius,
            max(
                WHEEL_ROTATION_MIN_RADIUS,
                visual_radius - WHEEL_ANCHOR_DRAG_SAFE_VISUAL_INSET_PX,
            ),
        )
    if max_radius:
        area_safe_radius = min(area_safe_radius, max_radius)
    return max(WHEEL_ROTATION_MIN_RADIUS, area_safe_radius)


def _outer_anchor_center_recovery_radius(previous, center_x, center_y, safe_drag_radius):
    if not previous:
        return None
    for key in (
        'handle_radius',
        'actual_radius',
        'radius',
        'signed_radius',
        'adaptive_handle_radius',
    ):
        try:
            radius = abs(float(previous.get(key)))
        except (TypeError, ValueError):
            continue
        if math.isfinite(radius) and radius > WHEEL_DIAMETER_CENTER_RESET_RADIUS:
            return min(max(radius, WHEEL_ROTATION_MIN_RADIUS), safe_drag_radius)
    try:
        dx = float(previous.get('x')) - float(center_x)
        dy = float(previous.get('y')) - float(center_y)
    except (TypeError, ValueError):
        return None
    radius = math.hypot(dx, dy)
    if math.isfinite(radius) and radius > WHEEL_DIAMETER_CENTER_RESET_RADIUS:
        return min(max(radius, WHEEL_ROTATION_MIN_RADIUS), safe_drag_radius)
    return None


def outer_anchor_reuse_state_context(area, state):
    center_x = state['center_x']
    center_y = state['center_y']
    wheel_radius = state.get('wheel_radius')
    visual_radius = state.get('visual_radius') or wheel_visual_radius(area, wheel_radius)
    handle_radius = state.get('handle_radius', 0.0)
    max_radius = wheel_orbit_safe_radius(area, state)
    safe_drag_radius = outer_anchor_drag_safe_radius(area, visual_radius, max_radius)
    if handle_radius > safe_drag_radius:
        handle_radius = safe_drag_radius
    start_angle = state.get('angle', -math.pi / 2)
    start_x = center_x + math.cos(start_angle) * handle_radius
    start_y = center_y + math.sin(start_angle) * handle_radius
    actual_radius = state.get('actual_radius', handle_radius)
    try:
        no_progress_count = int(state.get('no_progress_count', 0) or 0)
    except (TypeError, ValueError):
        no_progress_count = 0
    return {
        'center_x': center_x,
        'center_y': center_y,
        'visual_center_x': state.get('visual_center_x'),
        'visual_center_y': state.get('visual_center_y'),
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'handle_radius': handle_radius,
        'max_radius': max_radius,
        'safe_drag_radius': safe_drag_radius,
        'start_angle': start_angle,
        'start_x': start_x,
        'start_y': start_y,
        'actual_radius': actual_radius,
        'source': state.get('source') or 'anchor',
        'no_progress_count': no_progress_count,
    }


def outer_anchor_detected_handle_context(area, handle, previous=None):
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    visual_center_x = handle.get('visual_center_x')
    visual_center_y = handle.get('visual_center_y')
    wheel_radius = handle.get('wheel_radius')
    visual_radius = wheel_visual_radius(area, wheel_radius)
    max_radius = wheel_orbit_safe_radius(area, handle)
    safe_drag_radius = outer_anchor_drag_safe_radius(area, visual_radius, max_radius)
    dx = handle.get('x', center_x) - center_x
    dy = handle.get('y', center_y) - center_y
    actual_radius = math.hypot(dx, dy)
    center_like_handle = actual_radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS
    center_recovery_radius = None
    if center_like_handle:
        center_recovery_radius = _outer_anchor_center_recovery_radius(
            previous,
            center_x,
            center_y,
            safe_drag_radius,
        )
        start_angle = (
            previous.get('control_angle', previous.get('angle'))
            if previous
            else None
        )
        if start_angle is None:
            start_angle = -math.pi / 2
    elif actual_radius >= 2:
        start_angle = math.atan2(dy, dx)
    elif previous and previous.get('angle') is not None:
        start_angle = previous.get('angle')
    else:
        start_angle = -math.pi / 2
    if center_like_handle and center_recovery_radius is not None:
        handle_radius = center_recovery_radius
        actual_radius = center_recovery_radius
    elif center_like_handle:
        handle_radius = 0.0
    elif actual_radius <= WHEEL_ANCHOR_MIN_HANDLE_RADIUS:
        handle_radius = max(0.0, actual_radius)
    else:
        handle_radius = min(max(actual_radius, WHEEL_ROTATION_MIN_RADIUS), safe_drag_radius)
    return {
        'center_x': center_x,
        'center_y': center_y,
        'visual_center_x': visual_center_x,
        'visual_center_y': visual_center_y,
        'wheel_radius': wheel_radius,
        'visual_radius': visual_radius,
        'handle_radius': handle_radius,
        'max_radius': max_radius,
        'safe_drag_radius': safe_drag_radius,
        'start_angle': start_angle,
        'start_x': center_x + math.cos(start_angle) * handle_radius,
        'start_y': center_y + math.sin(start_angle) * handle_radius,
        'actual_radius': actual_radius,
        'center_recovery_radius': center_recovery_radius,
    }


def _bump_no_progress(no_progress_count):
    return min(no_progress_count + 1, WHEEL_ANCHOR_TOURBOX_STUCK_MAX_COUNT)


def _should_force_fresh_after_no_progress(next_no_progress_count):
    return (
        WHEEL_ANCHOR_FORCE_FRESH_NO_PROGRESS_COUNT > 0
        and next_no_progress_count >= WHEEL_ANCHOR_FORCE_FRESH_NO_PROGRESS_COUNT
    )


def _finite_float(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def outer_anchor_feedback_update(
    center_x,
    center_y,
    start_angle,
    target_state_angle,
    handle_radius,
    actual_radius,
    no_progress_count,
    near_center_anchor,
    feedback_handle,
    handle_active=True,
):
    start_handle_x = center_x + math.cos(start_angle) * handle_radius
    start_handle_y = center_y + math.sin(start_angle) * handle_radius
    target_handle_x = center_x + math.cos(target_state_angle) * handle_radius
    target_handle_y = center_y + math.sin(target_state_angle) * handle_radius
    result = {
        'state_angle': start_angle,
        'state_handle_x': start_handle_x,
        'state_handle_y': start_handle_y,
        'state_actual_radius': actual_radius,
        'next_no_progress_count': 0,
        'feedback_accepted': False,
        'feedback_ignored': False,
        'feedback_radius': None,
        'feedback_angle': None,
        'feedback_angle_error': None,
        'feedback_angle_limit_degrees': None,
        'feedback_radius_delta': None,
        'feedback_reject_reason': None,
        'force_fresh_handle': False,
        'requested_angle_delta': None,
        'feedback_angle_delta': None,
        'no_progress': False,
    }
    center_reference_radius = float('inf')
    center_candidate_radii = []
    for candidate_radius in (handle_radius, actual_radius):
        try:
            candidate_radius = abs(float(candidate_radius or 0.0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate_radius):
            center_candidate_radii.append(candidate_radius)
    if center_candidate_radii:
        center_reference_radius = min(center_candidate_radii)
    center_like_anchor = (
        near_center_anchor
        and center_reference_radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS
    )

    def use_center_prediction():
        result.update({
            'state_angle': target_state_angle,
            'state_handle_x': target_handle_x,
            'state_handle_y': target_handle_y,
            'state_actual_radius': actual_radius,
            'next_no_progress_count': 0,
            'force_fresh_handle': False,
        })

    if not feedback_handle:
        result['feedback_reject_reason'] = 'missing-feedback'
        if center_like_anchor:
            use_center_prediction()
            result['feedback_ignored'] = True
            return result
        result['force_fresh_handle'] = True
        if handle_active:
            next_no_progress_count = _bump_no_progress(no_progress_count)
            result['next_no_progress_count'] = next_no_progress_count
            if _should_force_fresh_after_no_progress(next_no_progress_count):
                result['feedback_reject_reason'] = 'missing-feedback'
        return result

    feedback_dx = feedback_handle['x'] - center_x
    feedback_dy = feedback_handle['y'] - center_y
    feedback_radius = math.hypot(feedback_dx, feedback_dy)
    result['feedback_radius'] = feedback_radius
    if near_center_anchor and feedback_radius <= WHEEL_DIAMETER_CENTER_RESET_RADIUS:
        center_like_anchor = True
    if feedback_radius < 2:
        if center_like_anchor:
            use_center_prediction()
            result['feedback_ignored'] = True
            result['feedback_reject_reason'] = 'center-tiny-feedback'
            return result
        result['force_fresh_handle'] = True
        next_no_progress_count = _bump_no_progress(no_progress_count)
        result['next_no_progress_count'] = next_no_progress_count
        if _should_force_fresh_after_no_progress(next_no_progress_count):
            result['force_fresh_handle'] = True
            result['feedback_reject_reason'] = 'tiny-feedback-radius'
        return result

    feedback_angle = math.atan2(feedback_dy, feedback_dx)
    feedback_angle_error = abs(normalize_angle_radians(feedback_angle - target_state_angle))
    reference_radius = abs(_finite_float(handle_radius))
    if reference_radius < 2:
        reference_radius = abs(_finite_float(actual_radius))
    if reference_radius < 2:
        reference_radius = feedback_radius
    feedback_radius_delta = abs(feedback_radius - reference_radius)
    feedback_angle_limit_degrees = (
        WHEEL_ANCHOR_NEAR_CENTER_FEEDBACK_MAX_ANGLE_ERROR_DEGREES
        if near_center_anchor
        else WHEEL_ANCHOR_FEEDBACK_MAX_ANGLE_ERROR_DEGREES
    )
    feedback_angle_limit = math.radians(feedback_angle_limit_degrees)

    result.update({
        'feedback_angle': feedback_angle,
        'feedback_angle_error': feedback_angle_error,
        'feedback_angle_limit_degrees': feedback_angle_limit_degrees,
        'feedback_radius_delta': feedback_radius_delta,
    })

    if center_like_anchor and feedback_radius > WHEEL_ANCHOR_NEAR_CENTER_RADIUS:
        use_center_prediction()
        result['feedback_ignored'] = True
        result['feedback_reject_reason'] = 'center-radius-outlier'
        result['next_no_progress_count'] = 0
        return result

    radius_outlier_limit = max(
        WHEEL_ANCHOR_FEEDBACK_RADIUS_OUTLIER_PX,
        reference_radius * 0.35,
    )
    if (
        not center_like_anchor
        and reference_radius >= 2
        and feedback_radius_delta > radius_outlier_limit
    ):
        result['feedback_ignored'] = True
        result['feedback_reject_reason'] = 'radius-outlier'
        result['force_fresh_handle'] = True
        result['next_no_progress_count'] = 0
        return result

    if feedback_angle_error > feedback_angle_limit:
        if center_like_anchor:
            use_center_prediction()
        result['feedback_ignored'] = True
        result['feedback_reject_reason'] = (
            'center-angle-error'
            if center_like_anchor
            else 'angle-error'
        )
        result['force_fresh_handle'] = not center_like_anchor
        result['next_no_progress_count'] = 0
        return result

    requested_angle_delta = abs(normalize_angle_radians(target_state_angle - start_angle))
    feedback_angle_delta = abs(normalize_angle_radians(feedback_angle - start_angle))
    min_progress = math.radians(WHEEL_ANCHOR_TOURBOX_STUCK_MIN_PROGRESS_DEGREES)
    no_progress = (
        requested_angle_delta >= min_progress
        and feedback_angle_delta < min_progress
    )
    next_no_progress_count = _bump_no_progress(no_progress_count) if no_progress else 0
    force_fresh_handle = _should_force_fresh_after_no_progress(next_no_progress_count)

    result.update({
        'state_angle': feedback_angle,
        'state_handle_x': center_x + math.cos(feedback_angle) * handle_radius,
        'state_handle_y': center_y + math.sin(feedback_angle) * handle_radius,
        'state_actual_radius': feedback_radius,
        'next_no_progress_count': next_no_progress_count,
        'feedback_accepted': True,
        'force_fresh_handle': force_fresh_handle,
        'feedback_reject_reason': 'no-progress' if force_fresh_handle else None,
        'requested_angle_delta': requested_angle_delta,
        'feedback_angle_delta': feedback_angle_delta,
        'no_progress': no_progress,
    })
    return result


__all__ = [
    'outer_anchor_drag_plan',
    'outer_anchor_drag_safe_radius',
    'outer_anchor_detected_handle_context',
    'outer_anchor_feedback_update',
    'outer_anchor_reuse_state_context',
    'outer_anchor_target',
]
