"""Adaptive angle prediction for outer-anchor wheel rotation."""

import math

from .config import (
    WHEEL_ANCHOR_ADAPTIVE_DEFAULT_DEGREES,
    WHEEL_ANCHOR_ADAPTIVE_DEGREES_ENABLED,
    WHEEL_ANCHOR_ADAPTIVE_DEGREES_MAX,
    WHEEL_ANCHOR_ADAPTIVE_DEGREES_MIN,
    WHEEL_ANCHOR_ADAPTIVE_MAX_CORRECTION_DEGREES,
    WHEEL_ANCHOR_ADAPTIVE_MIN_FEEDBACK_DEGREES,
)
from .wheel_common_geometry import normalize_angle_radians

ADAPTIVE_DEGREES_KEY = 'adaptive_degrees_per_tick'
ADAPTIVE_RADIUS_KEY = 'adaptive_handle_radius'


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_anchor_degrees_per_tick(value):
    value = _as_float(value)
    if value is None or not math.isfinite(value):
        value = WHEEL_ANCHOR_ADAPTIVE_DEFAULT_DEGREES
    return min(
        WHEEL_ANCHOR_ADAPTIVE_DEGREES_MAX,
        max(WHEEL_ANCHOR_ADAPTIVE_DEGREES_MIN, value),
    )


def resolve_anchor_degrees_per_tick(*sources, handle_radius=None):
    return clamp_anchor_degrees_per_tick(WHEEL_ANCHOR_ADAPTIVE_DEFAULT_DEGREES)


def update_anchor_degrees_per_tick(
    current_degrees,
    start_angle,
    predicted_angle,
    feedback_update,
    tick_units,
    source,
):
    current_degrees = clamp_anchor_degrees_per_tick(current_degrees)
    result = {
        'degrees_per_tick': current_degrees,
        'changed': False,
        'actual_degrees_per_tick': None,
        'raw_actual_degrees_per_tick': None,
        'correction_degrees': None,
        'requested_delta_degrees': None,
        'feedback_delta_degrees': None,
        'reason': None,
    }

    if not WHEEL_ANCHOR_ADAPTIVE_DEGREES_ENABLED:
        result['reason'] = 'disabled'
        return result
    if source != 'anchor':
        result['reason'] = f"source={source}"
        return result
    if not feedback_update.get('feedback_accepted'):
        result['reason'] = 'feedback-not-accepted'
        return result

    try:
        tick_units = abs(float(tick_units))
    except (TypeError, ValueError):
        tick_units = 0.0
    if tick_units <= 0.0:
        result['reason'] = 'zero-tick-units'
        return result

    feedback_angle = feedback_update.get('feedback_angle')
    if feedback_angle is None:
        result['reason'] = 'missing-feedback-angle'
        return result

    correction_degrees = math.degrees(
        normalize_angle_radians(feedback_angle - predicted_angle)
    )
    requested_delta = feedback_update.get('requested_angle_delta')
    if requested_delta is None:
        requested_delta = abs(normalize_angle_radians(predicted_angle - start_angle))
    feedback_delta = feedback_update.get('feedback_angle_delta')
    if feedback_delta is None:
        feedback_delta = abs(normalize_angle_radians(feedback_angle - start_angle))

    requested_delta_degrees = math.degrees(abs(requested_delta))
    feedback_delta_degrees = math.degrees(abs(feedback_delta))
    result.update({
        'correction_degrees': correction_degrees,
        'requested_delta_degrees': requested_delta_degrees,
        'feedback_delta_degrees': feedback_delta_degrees,
    })

    if abs(correction_degrees) > WHEEL_ANCHOR_ADAPTIVE_MAX_CORRECTION_DEGREES:
        result['reason'] = 'large-correction'
        return result
    if feedback_delta_degrees < WHEEL_ANCHOR_ADAPTIVE_MIN_FEEDBACK_DEGREES:
        result['reason'] = 'too-small-feedback'
        return result

    raw_actual_degrees_per_tick = feedback_delta_degrees / tick_units
    actual_degrees_per_tick = clamp_anchor_degrees_per_tick(raw_actual_degrees_per_tick)

    result.update({
        'degrees_per_tick': current_degrees,
        'changed': False,
        'actual_degrees_per_tick': actual_degrees_per_tick,
        'raw_actual_degrees_per_tick': raw_actual_degrees_per_tick,
        'reason': 'fixed-angle-observe',
    })
    return result


def anchor_adaptive_log_message(area_name, source, before_degrees, update):
    actual = update.get('actual_degrees_per_tick')
    actual_text = 'n/a' if actual is None else f"{actual:.2f}"
    raw_actual = update.get('raw_actual_degrees_per_tick')
    raw_actual_text = 'n/a' if raw_actual is None else f"{raw_actual:.2f}"
    correction = update.get('correction_degrees')
    correction_text = 'n/a' if correction is None else f"{correction:+.1f}"
    requested = update.get('requested_delta_degrees')
    requested_text = 'n/a' if requested is None else f"{requested:.1f}"
    feedback = update.get('feedback_delta_degrees')
    feedback_text = 'n/a' if feedback is None else f"{feedback:.1f}"
    return (
        f"outer-anchor adaptive {area_name}: source={source} "
        f"dpt={before_degrees:.2f}->{update['degrees_per_tick']:.2f} "
        f"actual={raw_actual_text} used={actual_text} correction={correction_text} "
        f"requested={requested_text} feedback={feedback_text} "
        f"reason={update.get('reason')}"
    )


__all__ = [
    'ADAPTIVE_DEGREES_KEY',
    'ADAPTIVE_RADIUS_KEY',
    'anchor_adaptive_log_message',
    'clamp_anchor_degrees_per_tick',
    'resolve_anchor_degrees_per_tick',
    'update_anchor_degrees_per_tick',
]
