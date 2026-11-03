"""Diameter axis-lock state helpers for wheel state ownership."""

import time

from .area_target_helpers import area_key
from .config import WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS
from .wheel_diameter_logic import wheel_diameter_axis_lock_for_area
from .wheel_common_geometry import normalize_angle_radians
from .wheel_state_diameter_payloads import wheel_diameter_axis_lock_payload


def set_wheel_diameter_axis_lock(
    manager,
    area,
    center_x,
    center_y,
    axis_angle,
    signed_radius,
    source='unknown',
    allow_center=False,
):
    if not area or area.get('type') != 'wheel' or axis_angle is None:
        return False

    target_key = area_key(area)
    area_name = area.get('name')
    if not target_key or not area_name:
        return False

    try:
        axis_angle = float(axis_angle)
        signed_radius = float(signed_radius or 0.0)
        center_x = float(center_x)
        center_y = float(center_y)
    except (TypeError, ValueError):
        return False

    if not allow_center and abs(signed_radius) < WHEEL_DIAMETER_AXIS_LOCK_MIN_RADIUS:
        return False

    manager._wheel_diameter_axis_lock = wheel_diameter_axis_lock_payload(
        target_key,
        area_name,
        center_x,
        center_y,
        normalize_angle_radians(axis_angle),
        signed_radius,
        source,
        updated_at=time.time(),
    )
    return True


def wheel_diameter_axis_lock_for_manager_area(manager, area, center_x=None, center_y=None):
    return wheel_diameter_axis_lock_for_area(
        manager._wheel_diameter_axis_lock,
        area_key(area) if area else None,
        area,
        center_x=center_x,
        center_y=center_y,
        now=time.time(),
    )


__all__ = [
    'set_wheel_diameter_axis_lock',
    'wheel_diameter_axis_lock_for_manager_area',
]
