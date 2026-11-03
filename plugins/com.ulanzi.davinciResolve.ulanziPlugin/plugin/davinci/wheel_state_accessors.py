"""Thin accessors and cleanup helpers for wheel state ownership."""

import time

from .area_target_helpers import area_key
from .config import WHEEL_SEGMENT_SESSION_SECONDS, WHEEL_TARGET_LOCK_SECONDS


def wheel_state_for_area(manager, area, center_x=None, center_y=None, wheel_radius=None):
    if not area or area.get('type') != 'wheel':
        return None
    return manager._wheel_state_store.get(
        area_key(area),
        area,
        center_x=center_x,
        center_y=center_y,
        wheel_radius=wheel_radius,
    )


def clear_wheel_anchor_state(manager):
    manager._wheel_anchor_state = None


def clear_wheel_diameter_state(manager):
    manager._wheel_diameter_state = None


def clear_wheel_segment_state(manager):
    manager._wheel_segment_state = None


def clear_wheel_state_store(manager):
    manager._wheel_state_store.clear()


def clear_wheel_target_lock(manager):
    manager._wheel_target_lock_area = None
    manager._wheel_target_lock_key = None
    manager._wheel_target_lock_until = 0.0


def clear_wheel_control_state(
    manager,
    *,
    clear_recent=False,
    clear_target_lock=False,
    clear_segment=False,
    clear_anchor=False,
    clear_diameter=False,
    clear_handles_cache=False,
    clear_state_store=False,
):
    if clear_recent or clear_target_lock or clear_segment or clear_anchor or clear_diameter:
        manager._wheel_dial_owner_context = None
        manager._wheel_dial_owner_at = 0.0
        manager._wheel_dial_owner_mode = None
    if clear_handles_cache:
        clear_wheel_handles(manager)
    if clear_recent:
        manager._last_wheel_area = None
        manager._last_wheel_at = 0.0
    if clear_target_lock:
        clear_wheel_target_lock(manager)
    if clear_segment:
        clear_wheel_segment_state(manager)
    if clear_anchor:
        clear_wheel_anchor_state(manager)
    if clear_diameter:
        clear_wheel_diameter_state(manager)
    if clear_state_store:
        clear_wheel_state_store(manager)


def wheel_anchor_state(manager):
    return manager._wheel_anchor_state


def wheel_diameter_state(manager):
    return manager._wheel_diameter_state


def wheel_segment_state(manager):
    return manager._wheel_segment_state


def wheel_handles(manager):
    return manager.handles


def wheel_handle_for_area(manager, area_name, default=None):
    if not area_name:
        return default
    return manager.handles.get(area_name, default)


def clear_wheel_handles(manager):
    manager.handles.clear()


def remove_wheel_handle(manager, area_name):
    if not area_name:
        return None
    return manager.handles.pop(area_name, None)


def wheel_drag_state(manager):
    return manager._wheel_drag


def set_wheel_drag_state(manager, drag):
    manager._wheel_drag = drag
    return drag


def wheel_orbit_state(manager):
    return manager._wheel_orbit


def set_wheel_orbit_state(manager, orbit):
    manager._wheel_orbit = orbit
    return orbit


def mark_recent_wheel_area(manager, area, *, updated_at=None):
    updated_at = time.time() if updated_at is None else updated_at
    manager._last_wheel_area = area
    manager._last_wheel_at = updated_at
    return updated_at


def recent_wheel_area(manager, *, max_age_seconds=WHEEL_SEGMENT_SESSION_SECONDS, now=None):
    now = time.time() if now is None else now
    if (
        manager._last_wheel_area
        and now - manager._last_wheel_at <= max_age_seconds
    ):
        return manager._last_wheel_area
    return None


def lock_wheel_target(manager, area, seconds=WHEEL_TARGET_LOCK_SECONDS, *, updated_at=None):
    if not area or area.get('type') != 'wheel':
        return False

    updated_at = time.time() if updated_at is None else updated_at
    manager._wheel_target_lock_area = area
    manager._wheel_target_lock_key = area_key(area)
    manager._wheel_target_lock_until = max(
        manager._wheel_target_lock_until,
        updated_at + seconds,
    )
    mark_recent_wheel_area(manager, area, updated_at=updated_at)
    return True


def is_wheel_target_locked(manager, *, now=None):
    now = time.time() if now is None else now
    return (
        manager._wheel_target_lock_area is not None
        and now < manager._wheel_target_lock_until
    )


def active_wheel_target_area(manager, *, now=None):
    now = time.time() if now is None else now
    if manager._manual_wheel_drag and manager._manual_wheel_drag.get('area'):
        return manager._manual_wheel_drag.get('area')
    drag = wheel_drag_state(manager)
    if drag and drag.get('area'):
        return drag.get('area')
    orbit = wheel_orbit_state(manager)
    if orbit and orbit.get('area'):
        return orbit.get('area')
    anchor = wheel_anchor_state(manager)
    if (
        anchor
        and anchor.get('area')
        and now - anchor.get('updated_at', 0) <= WHEEL_TARGET_LOCK_SECONDS
    ):
        return anchor.get('area')
    if is_wheel_target_locked(manager, now=now):
        return manager._wheel_target_lock_area
    return None


__all__ = [
    'active_wheel_target_area',
    'clear_wheel_anchor_state',
    'clear_wheel_control_state',
    'clear_wheel_diameter_state',
    'clear_wheel_handles',
    'clear_wheel_segment_state',
    'clear_wheel_state_store',
    'clear_wheel_target_lock',
    'is_wheel_target_locked',
    'lock_wheel_target',
    'mark_recent_wheel_area',
    'recent_wheel_area',
    'remove_wheel_handle',
    'set_wheel_drag_state',
    'set_wheel_orbit_state',
    'wheel_anchor_state',
    'wheel_diameter_state',
    'wheel_drag_state',
    'wheel_handle_for_area',
    'wheel_handles',
    'wheel_orbit_state',
    'wheel_segment_state',
    'wheel_state_for_area',
]
