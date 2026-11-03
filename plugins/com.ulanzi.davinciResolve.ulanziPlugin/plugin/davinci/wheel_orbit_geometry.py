"""Pure geometry helpers for wheel orbit motion."""

import math

from .config import (
    WHEEL_ARC_MAX_STEPS,
    WHEEL_ARC_STEP_DEGREES,
    WHEEL_ORBIT_ARC_MAX_STEPS,
    WHEEL_ORBIT_EDGE_GAIN_END_RATIO,
    WHEEL_ORBIT_EDGE_GAIN_START_RATIO,
    WHEEL_ORBIT_EDGE_MOUSE_DELTA_GAIN,
    WHEEL_ORBIT_MOUSE_DELTA_GAIN,
    WHEEL_ORBIT_OUTER_PRESS_INSET,
    WHEEL_ORBIT_OUTER_TANGENT_GAIN_SCALE,
    WHEEL_ORBIT_PROFILE_INNER_RATIO,
    WHEEL_ORBIT_PROFILE_OUTER_RATIO,
    WHEEL_ROTATION_MIN_RADIUS,
)


def build_wheel_arc_path(
    start_x,
    start_y,
    center_x,
    center_y,
    radius,
    start_angle,
    end_angle,
    step_degrees=WHEEL_ARC_STEP_DEGREES,
    max_steps=WHEEL_ARC_MAX_STEPS,
):
    delta_angle = end_angle - start_angle
    steps = min(
        max_steps,
        max(3, int(abs(math.degrees(delta_angle)) / step_degrees)),
    )
    points = [(start_x, start_y)]
    for step in range(1, steps + 1):
        t = step / steps
        angle = start_angle + delta_angle * t
        points.append((
            center_x + math.cos(angle) * radius,
            center_y + math.sin(angle) * radius,
        ))
    return points


def build_wheel_polar_delta(radius, start_angle, delta_angle, radial_correction=1.0):
    tangent_dx = -math.sin(start_angle) * radius * math.sin(delta_angle)
    tangent_dy = math.cos(start_angle) * radius * math.sin(delta_angle)
    inward = radius * (math.cos(delta_angle) - 1.0) * radial_correction
    radial_dx = math.cos(start_angle) * inward
    radial_dy = math.sin(start_angle) * inward
    return tangent_dx + radial_dx, tangent_dy + radial_dy


def build_wheel_tangent_vectors(radius, start_angle, end_angle, gain):
    delta_angle = end_angle - start_angle
    steps = min(
        WHEEL_ORBIT_ARC_MAX_STEPS,
        max(3, int(abs(math.degrees(delta_angle)) / WHEEL_ARC_STEP_DEGREES)),
    )
    vectors = []
    previous_angle = start_angle
    for step in range(1, steps + 1):
        angle = start_angle + delta_angle * step / steps
        step_angle = angle - previous_angle
        mid_angle = previous_angle + step_angle / 2
        length = radius * step_angle * gain
        vectors.append((
            -math.sin(mid_angle) * length,
            math.cos(mid_angle) * length,
        ))
        previous_angle = angle
    return vectors


def build_wheel_orbit_control_path(start_x, start_y, radius, start_angle, delta_angle, radial_correction):
    steps = min(
        WHEEL_ARC_MAX_STEPS,
        max(4, int(abs(math.degrees(delta_angle)) / WHEEL_ARC_STEP_DEGREES)),
    )
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        dx, dy = build_wheel_polar_delta(
            radius,
            start_angle,
            delta_angle * t,
            radial_correction,
        )
        points.append((start_x + dx, start_y + dy))
    return points


def wheel_orbit_outer_profile(radius, wheel_radius):
    if not wheel_radius or wheel_radius <= 0:
        return 0.0

    ratio = max(0.0, min(1.0, radius / wheel_radius))
    if ratio <= WHEEL_ORBIT_PROFILE_INNER_RATIO:
        return 0.0
    if ratio >= WHEEL_ORBIT_PROFILE_OUTER_RATIO:
        return 1.0
    span = WHEEL_ORBIT_PROFILE_OUTER_RATIO - WHEEL_ORBIT_PROFILE_INNER_RATIO
    return (ratio - WHEEL_ORBIT_PROFILE_INNER_RATIO) / span


def wheel_orbit_radial_correction(radius, wheel_radius):
    return 1.0 - wheel_orbit_outer_profile(radius, wheel_radius)


def wheel_orbit_gain_scale(radius, wheel_radius):
    outer = wheel_orbit_outer_profile(radius, wheel_radius)
    return 1.0 + (WHEEL_ORBIT_OUTER_TANGENT_GAIN_SCALE - 1.0) * outer


def wheel_orbit_mouse_start_point(center_x, center_y, angle, handle_x, handle_y, radius, wheel_radius):
    outer = wheel_orbit_outer_profile(radius, wheel_radius)
    if outer <= 0 or not wheel_radius or wheel_radius <= WHEEL_ORBIT_OUTER_PRESS_INSET:
        return handle_x, handle_y

    press_radius = min(
        radius,
        max(WHEEL_ROTATION_MIN_RADIUS, wheel_radius - WHEEL_ORBIT_OUTER_PRESS_INSET),
    )
    return (
        center_x + math.cos(angle) * press_radius,
        center_y + math.sin(angle) * press_radius,
    )


def build_relative_vectors_from_path(start_x, start_y, points):
    vectors = []
    previous_x = start_x
    previous_y = start_y
    for point_x, point_y in points:
        vectors.append((point_x - previous_x, point_y - previous_y))
        previous_x = point_x
        previous_y = point_y
    return vectors


def wheel_orbit_mouse_delta_gain(radius, wheel_radius):
    if not wheel_radius or wheel_radius <= 0:
        return WHEEL_ORBIT_MOUSE_DELTA_GAIN

    ratio = max(0.0, min(1.0, radius / wheel_radius))
    if ratio <= WHEEL_ORBIT_EDGE_GAIN_START_RATIO:
        return WHEEL_ORBIT_MOUSE_DELTA_GAIN
    if ratio >= WHEEL_ORBIT_EDGE_GAIN_END_RATIO:
        return WHEEL_ORBIT_EDGE_MOUSE_DELTA_GAIN

    span = WHEEL_ORBIT_EDGE_GAIN_END_RATIO - WHEEL_ORBIT_EDGE_GAIN_START_RATIO
    progress = (ratio - WHEEL_ORBIT_EDGE_GAIN_START_RATIO) / span
    return (
        WHEEL_ORBIT_MOUSE_DELTA_GAIN
        + (WHEEL_ORBIT_EDGE_MOUSE_DELTA_GAIN - WHEEL_ORBIT_MOUSE_DELTA_GAIN) * progress
    )


__all__ = [
    'build_relative_vectors_from_path',
    'build_wheel_arc_path',
    'build_wheel_orbit_control_path',
    'build_wheel_polar_delta',
    'build_wheel_tangent_vectors',
    'wheel_orbit_gain_scale',
    'wheel_orbit_mouse_delta_gain',
    'wheel_orbit_mouse_start_point',
    'wheel_orbit_outer_profile',
    'wheel_orbit_radial_correction',
]
