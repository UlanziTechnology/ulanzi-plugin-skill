"""Handle-cache commit helpers for wheel state ownership."""

import time

from .wheel_state_accessors import mark_recent_wheel_area
from .wheel_state_handle_payloads import (
    wheel_handle_payload,
    wheel_handle_timestamp_payload,
)
from .wheel_state_store_bridge import refresh_wheel_overlay_from_state_manager


def commit_wheel_detected_handle(
    manager,
    area,
    handle,
    *,
    area_name=None,
    updated_at=None,
    refresh_overlay=True,
):
    if not area or not handle:
        return None

    area_name = area_name or area.get('name')
    if not area_name:
        return None

    updated_at = time.time() if updated_at is None else updated_at
    stored_handle = wheel_handle_timestamp_payload(handle, updated_at=updated_at)
    manager.handles[area_name] = stored_handle
    if refresh_overlay:
        refresh_wheel_overlay_from_state_manager(manager, area, area_name)
    return stored_handle


def commit_wheel_raw_handle(
    manager,
    area,
    handle,
    *,
    area_name=None,
    updated_at=None,
    refresh_overlay=False,
):
    if not area or not handle:
        return None

    area_name = area_name or area.get('name')
    if not area_name:
        return None

    stored_handle = handle
    if updated_at is not None:
        stored_handle = wheel_handle_timestamp_payload(handle, updated_at=updated_at)
    manager.handles[area_name] = stored_handle
    if refresh_overlay:
        refresh_wheel_overlay_from_state_manager(manager, area, area_name)
    return stored_handle


def commit_wheel_predicted_handle(
    manager,
    area,
    area_name,
    center_x,
    center_y,
    wheel_radius,
    handle_x,
    handle_y,
    angle,
    signed_radius,
    *,
    updated_at=None,
    mark_recent=False,
):
    if not area or not area_name:
        return None

    updated_at = time.time() if updated_at is None else updated_at
    stored_handle = wheel_handle_payload(
        center_x,
        center_y,
        wheel_radius,
        handle_x,
        handle_y,
        angle,
        angle,
        signed_radius,
        updated_at=updated_at,
    )
    manager.handles[area_name] = stored_handle
    if mark_recent:
        mark_recent_wheel_area(manager, area, updated_at=updated_at)
    return stored_handle


__all__ = [
    'commit_wheel_detected_handle',
    'commit_wheel_predicted_handle',
    'commit_wheel_raw_handle',
]
