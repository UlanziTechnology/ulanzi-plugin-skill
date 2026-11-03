"""Pure geometry helpers for wheel diameter push/pull motion."""

import math

from .config import (
    WHEEL_DIAMETER_AREA_MAX_RADIUS_RATIO,
    WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS,
    WHEEL_DIAMETER_CENTER_BYPASS_RADIUS,
    WHEEL_DIAMETER_CENTER_CROSS_EPSILON,
    WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS,
    WHEEL_DIAMETER_EDGE_PADDING,
    WHEEL_DIAMETER_HORIZONTAL_EPSILON_PX,
    WHEEL_DIAMETER_MAX_RADIUS_RATIO,
    WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS,
    WHEEL_DIAMETER_OUTER_BRIDGE_RADIUS_RATIO,
    WHEEL_DIAMETER_OUTER_CONTROL_NUDGE_PX,
    WHEEL_DIAMETER_OUTER_CONTROL_RADIUS_RATIO,
    WHEEL_DIAMETER_OUTER_PRESS_INSET,
    WHEEL_DIAMETER_OUTER_PRESS_START_RATIO,
    WHEEL_DIAMETER_SAFE_PRESS_ENABLED,
    WHEEL_DIAMETER_SAFE_PRESS_MAX_RADIUS,
    WHEEL_DIAMETER_SAFE_PRESS_MIN_RADIUS,
    WHEEL_DIAMETER_SAFE_PRESS_RADIUS_RATIO,
    WHEEL_DIAMETER_SAFE_PRESS_START_RATIO,
    WHEEL_DIAMETER_VERTICAL_EPSILON_PX,
    WHEEL_ROTATION_MIN_RADIUS,
)
from .wheel_common_geometry import build_linear_path, normalize_angle_radians


def wheel_diameter_axis_from_vector(dx, dy, radius):
    if abs(dy) <= WHEEL_DIAMETER_HORIZONTAL_EPSILON_PX and abs(dx) >= 2:
        return 0.0, dx

    if abs(dx) <= WHEEL_DIAMETER_VERTICAL_EPSILON_PX and abs(dy) >= 2:
        return -math.pi / 2, -dy

    if radius < WHEEL_ROTATION_MIN_RADIUS:
        return -math.pi / 2, 0.0

    angle = math.atan2(dy, dx)
    if math.sin(angle) > 0:
        return normalize_angle_radians(angle + math.pi), -radius

    return normalize_angle_radians(angle), radius


def wheel_diameter_axis_from_small_vector(dx, dy, radius):
    if radius < WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS:
        return None

    angle = math.atan2(dy, dx)
    if math.sin(angle) > 0:
        return normalize_angle_radians(angle + math.pi), -radius

    return normalize_angle_radians(angle), radius


def wheel_diameter_point(center_x, center_y, axis_angle, signed_radius):
    return (
        center_x + math.cos(axis_angle) * signed_radius,
        center_y + math.sin(axis_angle) * signed_radius,
    )


def wheel_diameter_outer_control_radius(area, center_x, center_y, wheel_radius, max_radius):
    if wheel_radius and wheel_radius > 0:
        desired_radius = wheel_radius * WHEEL_DIAMETER_OUTER_CONTROL_RADIUS_RATIO
    else:
        desired_radius = max_radius

    area_radius = min(
        center_x - area['x'],
        area['x'] + area['w'] - center_x,
        center_y - area['y'],
        area['y'] + area['h'] - center_y,
    )
    return max(6.0, min(max(desired_radius, max_radius), max(6.0, area_radius)))


def wheel_diameter_outer_control_point(center_x, center_y, axis_angle, signed_radius, outer_radius):
    control_angle = wheel_diameter_display_angle(axis_angle, signed_radius)
    return (
        center_x + math.cos(control_angle) * outer_radius,
        center_y + math.sin(control_angle) * outer_radius,
        control_angle,
    )


def build_wheel_diameter_outer_jump_path(
    center_x,
    center_y,
    axis_angle,
    target_signed_radius,
    max_radius,
):
    target_x, target_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        target_signed_radius,
    )
    if abs(target_signed_radius) >= max_radius - WHEEL_DIAMETER_OUTER_CONTROL_NUDGE_PX:
        return [(target_x, target_y)]

    nudge_signed_radius = target_signed_radius + math.copysign(
        WHEEL_DIAMETER_OUTER_CONTROL_NUDGE_PX,
        target_signed_radius or 1.0,
    )
    nudge_signed_radius = max(-max_radius, min(max_radius, nudge_signed_radius))
    nudge_x, nudge_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        nudge_signed_radius,
    )
    return [(nudge_x, nudge_y), (target_x, target_y)]


def build_wheel_diameter_outer_bridge_path(
    center_x,
    center_y,
    axis_angle,
    start_x,
    start_y,
    start_signed_radius,
    target_x,
    target_y,
    target_signed_radius,
    max_radius,
    steps,
):
    start_sign = -1.0 if start_signed_radius < 0 else 1.0
    target_sign = -1.0 if target_signed_radius < 0 else 1.0
    if start_sign == target_sign or max_radius <= WHEEL_ROTATION_MIN_RADIUS:
        return build_linear_path(start_x, start_y, target_x, target_y, steps=steps)

    bridge_radius = max(
        WHEEL_ROTATION_MIN_RADIUS,
        min(max_radius, max_radius * WHEEL_DIAMETER_OUTER_BRIDGE_RADIUS_RATIO),
    )
    start_bridge_x, start_bridge_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        start_sign * bridge_radius,
    )
    target_bridge_x, target_bridge_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        target_sign * bridge_radius,
    )

    steps = max(WHEEL_DIAMETER_OUTER_BRIDGE_MIN_STEPS, int(steps))
    lead_steps = max(3, steps // 4)
    arc_steps = max(8, steps // 2)
    finish_steps = max(3, steps - lead_steps - arc_steps)

    path = []
    path.extend(build_linear_path(
        start_x,
        start_y,
        start_bridge_x,
        start_bridge_y,
        steps=lead_steps,
    ))

    start_angle = axis_angle if start_sign > 0 else axis_angle + math.pi
    delta_angle = math.pi if target_sign > start_sign else -math.pi
    for step in range(1, arc_steps + 1):
        angle = start_angle + delta_angle * step / arc_steps
        path.append((
            center_x + math.cos(angle) * bridge_radius,
            center_y + math.sin(angle) * bridge_radius,
        ))

    path.extend(build_linear_path(
        target_bridge_x,
        target_bridge_y,
        target_x,
        target_y,
        steps=finish_steps,
    ))
    return path


def build_wheel_diameter_center_cross_path(
    center_x,
    center_y,
    axis_angle,
    start_x,
    start_y,
    start_signed_radius,
    target_x,
    target_y,
    target_signed_radius,
    max_radius,
    steps,
):
    start_sign = -1.0 if start_signed_radius < 0 else 1.0
    target_sign = -1.0 if target_signed_radius < 0 else 1.0
    if start_sign == target_sign or max_radius <= WHEEL_DIAMETER_CENTER_CROSS_EPSILON:
        return build_linear_path(start_x, start_y, target_x, target_y, steps=steps)

    bridge_radius = min(
        max_radius,
        WHEEL_DIAMETER_CENTER_BYPASS_RADIUS,
    )
    if bridge_radius <= WHEEL_DIAMETER_CENTER_CROSS_EPSILON:
        return build_linear_path(start_x, start_y, target_x, target_y, steps=steps)

    start_bridge_x, start_bridge_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        start_sign * bridge_radius,
    )
    target_bridge_x, target_bridge_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        target_sign * bridge_radius,
    )

    steps = max(WHEEL_DIAMETER_CENTER_CROSS_MIN_STEPS, int(steps))
    lead_steps = 1
    arc_steps = max(4, steps // 2)
    finish_steps = max(2, steps - lead_steps - arc_steps)

    path = []
    path.extend(build_linear_path(
        start_x,
        start_y,
        start_bridge_x,
        start_bridge_y,
        steps=lead_steps,
    ))

    start_angle = axis_angle if start_sign > 0 else axis_angle + math.pi
    delta_angle = math.pi if target_sign > start_sign else -math.pi
    for step in range(1, arc_steps + 1):
        angle = start_angle + delta_angle * step / arc_steps
        path.append((
            center_x + math.cos(angle) * bridge_radius,
            center_y + math.sin(angle) * bridge_radius,
        ))

    path.extend(build_linear_path(
        target_bridge_x,
        target_bridge_y,
        target_x,
        target_y,
        steps=finish_steps,
    ))
    return path


def wheel_diameter_mouse_start_point(center_x, center_y, axis_angle, signed_radius, handle_x, handle_y, max_radius):
    handle_radius = math.hypot(handle_x - center_x, handle_y - center_y)
    active_radius = max(abs(signed_radius), handle_radius)
    if (
        max_radius <= WHEEL_ROTATION_MIN_RADIUS
        or active_radius < max_radius * WHEEL_DIAMETER_OUTER_PRESS_START_RATIO
    ):
        return handle_x, handle_y

    inset = min(
        WHEEL_DIAMETER_OUTER_PRESS_INSET,
        max(0.0, active_radius - WHEEL_ROTATION_MIN_RADIUS),
    )
    press_signed_radius = signed_radius - math.copysign(inset, signed_radius or 1.0)
    return wheel_diameter_point(center_x, center_y, axis_angle, press_signed_radius)


def wheel_diameter_safe_press_point(center_x, center_y, axis_angle, signed_radius, handle_x, handle_y, max_radius):
    if not WHEEL_DIAMETER_SAFE_PRESS_ENABLED or max_radius <= WHEEL_ROTATION_MIN_RADIUS:
        return handle_x, handle_y

    handle_radius = math.hypot(handle_x - center_x, handle_y - center_y)
    active_radius = max(abs(signed_radius), handle_radius)
    if active_radius < max_radius * WHEEL_DIAMETER_SAFE_PRESS_START_RATIO:
        return handle_x, handle_y

    safe_radius = min(
        max_radius * WHEEL_DIAMETER_SAFE_PRESS_RADIUS_RATIO,
        WHEEL_DIAMETER_SAFE_PRESS_MAX_RADIUS,
    )
    safe_radius = max(
        WHEEL_DIAMETER_SAFE_PRESS_MIN_RADIUS,
        min(safe_radius, max_radius - WHEEL_DIAMETER_EDGE_PADDING),
    )
    if active_radius <= safe_radius:
        return handle_x, handle_y

    sign_source = signed_radius
    if abs(sign_source) < 0.1:
        sign_source = (
            (handle_x - center_x) * math.cos(axis_angle)
            + (handle_y - center_y) * math.sin(axis_angle)
        )
    press_signed_radius = math.copysign(safe_radius, sign_source or 1.0)
    return wheel_diameter_point(center_x, center_y, axis_angle, press_signed_radius)


def wheel_diameter_display_angle(axis_angle, signed_radius):
    if signed_radius < 0:
        return normalize_angle_radians(axis_angle + math.pi)
    return normalize_angle_radians(axis_angle)


def wheel_diameter_project_handle_to_axis(handle, center_x, center_y, axis_angle, max_radius=None):
    raw_x = float(handle['x'])
    raw_y = float(handle['y'])
    dx = raw_x - center_x
    dy = raw_y - center_y
    signed_radius = dx * math.cos(axis_angle) + dy * math.sin(axis_angle)
    cross_offset = -dx * math.sin(axis_angle) + dy * math.cos(axis_angle)

    if max_radius is not None and max_radius > 0:
        signed_radius = max(-max_radius, min(max_radius, signed_radius))

    projected_x, projected_y = wheel_diameter_point(
        center_x,
        center_y,
        axis_angle,
        signed_radius,
    )
    projected = dict(handle)
    projected.update({
        'x': projected_x,
        'y': projected_y,
        'raw_x': raw_x,
        'raw_y': raw_y,
        'angle': wheel_diameter_display_angle(axis_angle, signed_radius),
        'radial_axis_angle': axis_angle,
        'signed_radius': signed_radius,
        'radius': abs(signed_radius),
        'axis_cross_offset': cross_offset,
        'source': f"{handle.get('source', 'handle')}_axis_projected",
    })
    return projected, signed_radius, cross_offset


def wheel_diameter_max_radius(area, center_x, center_y, wheel_radius):
    candidates = []
    if wheel_radius:
        candidates.append(
            max(
                6,
                min(
                    max(6, wheel_radius - WHEEL_DIAMETER_EDGE_PADDING),
                    max(6, wheel_radius * WHEEL_DIAMETER_MAX_RADIUS_RATIO),
                ),
            )
        )

    area_radius = min(
        center_x - area['x'],
        area['x'] + area['w'] - center_x,
        center_y - area['y'],
        area['y'] + area['h'] - center_y,
    )
    candidates.append(max(6, area_radius * WHEEL_DIAMETER_AREA_MAX_RADIUS_RATIO))
    return max(candidates)


__all__ = [
    'build_wheel_diameter_center_cross_path',
    'build_wheel_diameter_outer_bridge_path',
    'build_wheel_diameter_outer_jump_path',
    'wheel_diameter_axis_from_vector',
    'wheel_diameter_axis_from_small_vector',
    'wheel_diameter_display_angle',
    'wheel_diameter_max_radius',
    'wheel_diameter_mouse_start_point',
    'wheel_diameter_outer_control_point',
    'wheel_diameter_outer_control_radius',
    'wheel_diameter_point',
    'wheel_diameter_project_handle_to_axis',
    'wheel_diameter_safe_press_point',
]
