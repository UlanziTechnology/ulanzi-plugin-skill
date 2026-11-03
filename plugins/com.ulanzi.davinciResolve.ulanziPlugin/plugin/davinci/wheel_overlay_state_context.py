"""Overlay state calculation and refresh helpers for wheel controls."""

import time

from .area_target_helpers import area_key
from .config import WHEEL_HANDLE_CACHE_SECONDS
from .layout_scan_guard import smooth_layout_busy
from .wheel_overlay_visibility import hide_inactive_overlays
from .wheel_state_accessors import (
    wheel_anchor_state,
    wheel_diameter_state,
    wheel_handle_for_area,
    wheel_handles,
)
from .wheel_state_detection_commits import store_hover_wheel_handle_from_detection
from .wheel_visual_state import wheel_overlay_state_for_area


def wheel_overlay_state(manager, area):
    if not area or area.get('type') != 'wheel':
        return None

    area_name = area.get('name')
    area_key_value = area_key(area)
    overlay = wheel_overlay_state_for_area(
        area,
        area_key_value,
        area_name,
        wheel_anchor_state(manager),
        wheel_diameter_state(manager),
        wheel_handles(manager),
        time.time(),
    )
    handle = overlay.get('handle')
    if handle is not None:
        handle.update(overlay['handle_updates'])
    return overlay.get('state')


def refresh_wheel_overlay_state(manager, area, area_name=None):
    if not area or area.get('type') != 'wheel':
        return
    key = area_key(area)
    overlay = manager.overlays.get(key)
    if overlay:
        overlay.update_wheel_state(wheel_overlay_state(manager, area))


def refresh_existing_hover_overlay(manager, area, key):
    hide_inactive_overlays(manager, key)
    if manager._hover_visible_key != key:
        return False
    overlay = manager.overlays.get(key)
    if not overlay:
        return False
    overlay.update_area(area)
    overlay.update_wheel_state(wheel_overlay_state(manager, area))
    return True


def ensure_wheel_handle_for_overlay(
    manager,
    area,
    detect_handle_raw_for_area_fn,
    debug_slow_fn=None,
):
    if not area or area.get('type') != 'wheel':
        return False

    area_name = area.get('name')
    if not area_name:
        return False

    now = time.time()
    previous = wheel_handle_for_area(manager, area_name)
    if smooth_layout_busy(manager):
        # A stale overlay cache must not start pixel recognition during motion.
        return bool(previous and previous.get('x') is not None and previous.get('y') is not None)
    previous_source = str(previous.get('source', '')) if previous else ''
    previous_from_smooth = previous_source.startswith('smooth_')
    previous_from_diameter = bool(
        previous
        and not previous_from_smooth
        and (
            previous_source.startswith('diameter')
            or previous.get('effective_max_radius') is not None
        )
    )
    if (
        previous
        and previous.get('x') is not None
        and previous.get('y') is not None
        and now - previous.get('updated_at', 0) <= WHEEL_HANDLE_CACHE_SECONDS
        and not previous_from_diameter
    ):
        return True

    handle = detect_handle_raw_for_area_fn(area)
    if not handle:
        return False

    return store_hover_wheel_handle_from_detection(
        manager,
        area,
        handle,
        source='hover_detect',
        updated_at=now,
        debug_slow_fn=debug_slow_fn,
    )


__all__ = [
    'ensure_wheel_handle_for_overlay',
    'refresh_existing_hover_overlay',
    'refresh_wheel_overlay_state',
    'wheel_overlay_state',
]
