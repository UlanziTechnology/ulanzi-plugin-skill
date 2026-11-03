"""Paint-time visual calculations for DaVinci wheel overlays."""

import math

from .config import (
    OVERLAY_WHEEL_DOT_RADIUS,
    OVERLAY_WHEEL_DOT_SOFT_PADDING,
    OVERLAY_WHEEL_DOT_TRACK_GAP,
    OVERLAY_WHEEL_RING_FALLBACK_RATIO,
    OVERLAY_WHEEL_VISUAL_CENTER_OFFSET_X,
    OVERLAY_WHEEL_VISUAL_CENTER_OFFSET_Y,
)
from .overlay_colors import _wheel_hue_hex
from .wheel_confirmed_geometry import confirmed_geometry_for_area


def _float_value(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def wheel_state_for_paint(
    area,
    state,
    overlay_geometry,
    wheel_dot_hidden=False,
    allow_dot_outside=False,
):
    if not area or area.get('type') != 'wheel':
        return None
    if wheel_dot_hidden or (state or {}).get('visual_invalidated'):
        return None

    overlay_x, overlay_y, w, h = overlay_geometry
    state = state or {}
    confirmed = confirmed_geometry_for_area(area)
    if confirmed is not None:
        # Motion owns the angle, not the measured layout's display geometry.
        state = {**state,
                 'center_x': confirmed['wheel_center_x'],
                 'center_y': confirmed['wheel_center_y'],
                 'visual_center_x': confirmed['visual_center_x'],
                 'visual_center_y': confirmed['visual_center_y'],
                 'wheel_radius': confirmed['wheel_radius']}
    center_x = _float_value(
        state.get('center_x'),
        area.get('center_x', area['x'] + area['w'] / 2),
    )
    center_y = _float_value(
        state.get('center_y'),
        area.get('center_y', area['y'] + area['h'] / 2),
    )
    visual_center_x = _float_value(state.get('visual_center_x'), center_x)
    visual_center_y = _float_value(state.get('visual_center_y'), center_y)
    if center_x is None or center_y is None:
        return None

    cx = visual_center_x - overlay_x
    cy = visual_center_y - overlay_y
    visual_cx = cx + OVERLAY_WHEEL_VISUAL_CENTER_OFFSET_X
    visual_cy = cy + OVERLAY_WHEEL_VISUAL_CENTER_OFFSET_Y
    dot_inset = OVERLAY_WHEEL_DOT_RADIUS + OVERLAY_WHEEL_DOT_SOFT_PADDING + 1
    if (
        visual_cx <= dot_inset
        or visual_cy <= dot_inset
        or visual_cx >= w - dot_inset
        or visual_cy >= h - dot_inset
    ):
        return None

    radius = _float_value(state.get('wheel_radius'))
    if radius is None:
        radius = min(area['w'], area['h']) * OVERLAY_WHEEL_RING_FALLBACK_RATIO
    radius = max(6.0, float(radius))

    angle = _float_value(
        state.get('control_angle'),
        state.get('angle'),
    )
    if angle is None:
        angle = -math.pi / 2

    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    color = state.get('color') or _wheel_hue_hex(angle)
    # ``outer_control_radius`` belongs to pointer/gesture geometry and remains
    # deliberately farther out.  The display dot instead rides over Resolve's
    # black ring while remaining independent from the gesture control radius.
    requested_dot_distance = max(6.0, radius + OVERLAY_WHEEL_DOT_TRACK_GAP)
    # Paint from angle + radius so cached screen-space outer points cannot make
    # the visual dot sit closer/farther on different sides of the same wheel.
    # Native dot windows are independent from the corner overlay, so they should
    # keep the fixed outer radius instead of being clipped by the overlay bounds.
    if allow_dot_outside:
        dot_distance = requested_dot_distance
    else:
        max_dot_distance = float('inf')
        if cos_angle > 0.0001:
            max_dot_distance = min(max_dot_distance, (w - dot_inset - visual_cx) / cos_angle)
        elif cos_angle < -0.0001:
            max_dot_distance = min(max_dot_distance, (visual_cx - dot_inset) / -cos_angle)
        if sin_angle > 0.0001:
            max_dot_distance = min(max_dot_distance, (h - dot_inset - visual_cy) / sin_angle)
        elif sin_angle < -0.0001:
            max_dot_distance = min(max_dot_distance, (visual_cy - dot_inset) / -sin_angle)
        if not math.isfinite(max_dot_distance):
            max_dot_distance = radius + OVERLAY_WHEEL_DOT_TRACK_GAP
        dot_distance = min(requested_dot_distance, max_dot_distance)
    dot_distance = max(6.0, dot_distance)
    px = visual_cx + cos_angle * dot_distance
    py = visual_cy + sin_angle * dot_distance

    return {
        'cx': visual_cx,
        'cy': visual_cy,
        'radius': radius,
        'dot_distance': dot_distance,
        'angle': angle,
        'px': px,
        'py': py,
        'color': color,
    }


__all__ = ['wheel_state_for_paint']
