"""Orbit input model helpers for DaVinci color wheels."""

import math

from .config import (
    WHEEL_ANCHOR_TOURBOX_TANGENT_MAX_STEPS,
    WHEEL_ANCHOR_TOURBOX_TANGENT_PIXELS_PER_TICK,
    WHEEL_ANCHOR_TOURBOX_TANGENT_STEP_PX,
    WHEEL_EDGE_PADDING,
    WHEEL_ORBIT_ARC_ANGLE_GAIN,
    WHEEL_ORBIT_EDGE_PADDING,
    WHEEL_ORBIT_MAX_RADIUS_RATIO,
    WHEEL_ORBIT_REDETECT_SEGMENTS,
    WHEEL_ORBIT_SHORT_ARC_MAX_DEGREES,
    WHEEL_ORBIT_SHORT_ARC_MAX_STEPS,
    WHEEL_ORBIT_SHORT_ARC_STEP_DEGREES,
    WHEEL_ORBIT_STATE_IDLE_SECONDS,
    WHEEL_ROTATE_DEGREES_PER_TICK,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_orbit_geometry import build_wheel_arc_path
from .wheel_state_helpers import clamp_max_radius_with_effective


def build_tourbox_tangent_orbit_path(
    start_x,
    start_y,
    start_angle,
    ticks,
    sensitivity,
    radial_pull_px=0.0,
):
    distance = (
        float(ticks)
        * float(sensitivity)
        * WHEEL_ANCHOR_TOURBOX_TANGENT_PIXELS_PER_TICK
    )
    radial_pull_px = max(0.0, float(radial_pull_px or 0.0))
    move_x = -math.sin(start_angle) * distance - math.cos(start_angle) * radial_pull_px
    move_y = math.cos(start_angle) * distance - math.sin(start_angle) * radial_pull_px
    total_distance = math.hypot(move_x, move_y)
    steps = max(
        2,
        min(
            WHEEL_ANCHOR_TOURBOX_TANGENT_MAX_STEPS,
            int(math.ceil(total_distance / WHEEL_ANCHOR_TOURBOX_TANGENT_STEP_PX)),
        ),
    )
    path = [
        (
            start_x + move_x * index / steps,
            start_y + move_y * index / steps,
        )
        for index in range(1, steps + 1)
    ]
    return path, move_x, move_y, total_distance


def wheel_orbit_safe_radius(area, handle):
    wheel_radius = handle.get('wheel_radius')
    if wheel_radius:
        safe_radius = max(
            WHEEL_ROTATION_MIN_RADIUS,
            min(
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius - WHEEL_ORBIT_EDGE_PADDING),
                max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius * WHEEL_ORBIT_MAX_RADIUS_RATIO),
            ),
        )
    else:
        safe_radius = max(WHEEL_ROTATION_MIN_RADIUS, min(area['w'], area['h']) / 2 - WHEEL_EDGE_PADDING)
    return clamp_max_radius_with_effective(
        safe_radius,
        handle.get('effective_max_radius') if isinstance(handle, dict) else None,
    )


def wheel_orbit_short_arc_plan(
    center_x,
    center_y,
    start_x,
    start_y,
    start_angle,
    locked_radius,
    ticks,
    sensitivity,
):
    base_delta_angle = math.radians(ticks * sensitivity * WHEEL_ROTATE_DEGREES_PER_TICK)
    max_delta_angle = math.radians(WHEEL_ORBIT_SHORT_ARC_MAX_DEGREES)
    delta_angle = max(
        -max_delta_angle,
        min(max_delta_angle, base_delta_angle * WHEEL_ORBIT_ARC_ANGLE_GAIN),
    )
    target_angle = start_angle + delta_angle
    target_x = center_x + math.cos(target_angle) * locked_radius
    target_y = center_y + math.sin(target_angle) * locked_radius
    return {
        'base_delta_angle': base_delta_angle,
        'delta_angle': delta_angle,
        'target_angle': target_angle,
        'target_x': target_x,
        'target_y': target_y,
        'handle_path': build_wheel_arc_path(
            start_x,
            start_y,
            center_x,
            center_y,
            locked_radius,
            start_angle,
            target_angle,
            step_degrees=WHEEL_ORBIT_SHORT_ARC_STEP_DEGREES,
            max_steps=WHEEL_ORBIT_SHORT_ARC_MAX_STEPS,
        ),
    }


def wheel_orbit_reuse_context(orbit, target_key, now):
    reuse_orbit = bool(
        orbit
        and orbit.get('target_key') == target_key
        and now - orbit.get('last_at', 0) <= WHEEL_ORBIT_STATE_IDLE_SECONDS
        and orbit.get('segment_count', 0) < WHEEL_ORBIT_REDETECT_SEGMENTS
    )
    reuse_dragging = bool(reuse_orbit and orbit.get('dragging'))
    if not reuse_orbit:
        return {
            'reuse_orbit': False,
            'reuse_dragging': False,
        }

    start_x = orbit['handle_x']
    start_y = orbit['handle_y']
    return {
        'reuse_orbit': True,
        'reuse_dragging': reuse_dragging,
        'center_x': orbit['center_x'],
        'center_y': orbit['center_y'],
        'locked_radius': orbit['radius'],
        'start_angle': orbit['angle'],
        'start_x': start_x,
        'start_y': start_y,
        'actual_radius': orbit.get('actual_radius', orbit['radius']),
        'wheel_radius_value': orbit.get('wheel_radius'),
        'start_mouse_x': orbit.get('x', start_x) if reuse_dragging else start_x,
        'start_mouse_y': orbit.get('y', start_y) if reuse_dragging else start_y,
        'segment_count': orbit.get('segment_count', 0),
        'source': 'dragging' if reuse_dragging else 'predicted',
    }


def wheel_orbit_detected_context(area, handle, max_radius):
    center_x = handle.get('wheel_center_x', area.get('center_x', area['x'] + area['w'] / 2))
    center_y = handle.get('wheel_center_y', area.get('center_y', area['y'] + area['h'] / 2))
    wheel_radius_value = handle.get('wheel_radius')
    actual_dx = handle['x'] - center_x
    actual_dy = handle['y'] - center_y
    actual_radius = math.hypot(actual_dx, actual_dy)
    start_angle = math.atan2(actual_dy, actual_dx) if actual_radius >= 2 else handle.get('angle', 0.0)
    locked_radius = min(max(WHEEL_ROTATION_MIN_RADIUS, actual_radius), max_radius)
    if actual_radius > locked_radius + 1:
        start_x = center_x + math.cos(start_angle) * locked_radius
        start_y = center_y + math.sin(start_angle) * locked_radius
    else:
        start_x = handle['x']
        start_y = handle['y']
    return {
        'center_x': center_x,
        'center_y': center_y,
        'locked_radius': locked_radius,
        'start_angle': start_angle,
        'start_x': start_x,
        'start_y': start_y,
        'actual_radius': actual_radius,
        'wheel_radius_value': wheel_radius_value,
        'start_mouse_x': start_x,
        'start_mouse_y': start_y,
        'segment_count': 0,
        'source': 'detected',
    }


def wheel_orbit_feedback_state(
    center_x,
    center_y,
    locked_radius,
    actual_radius,
    target_angle,
    target_x,
    target_y,
    feedback_handle=None,
):
    state_angle = target_angle
    state_handle_x = target_x
    state_handle_y = target_y
    state_actual_radius = actual_radius
    output_handle_x = target_x
    output_handle_y = target_y
    if feedback_handle:
        output_handle_x = feedback_handle['x']
        output_handle_y = feedback_handle['y']
        feedback_dx = feedback_handle['x'] - center_x
        feedback_dy = feedback_handle['y'] - center_y
        feedback_radius = math.hypot(feedback_dx, feedback_dy)
        if feedback_radius >= 2:
            state_angle = math.atan2(feedback_dy, feedback_dx)
            state_handle_x = center_x + math.cos(state_angle) * locked_radius
            state_handle_y = center_y + math.sin(state_angle) * locked_radius
            state_actual_radius = feedback_radius
    return {
        'state_angle': state_angle,
        'state_handle_x': state_handle_x,
        'state_handle_y': state_handle_y,
        'state_actual_radius': state_actual_radius,
        'output_handle_x': output_handle_x,
        'output_handle_y': output_handle_y,
    }


__all__ = [
    'build_tourbox_tangent_orbit_path',
    'wheel_orbit_detected_context',
    'wheel_orbit_feedback_state',
    'wheel_orbit_reuse_context',
    'wheel_orbit_safe_radius',
    'wheel_orbit_short_arc_plan',
]
