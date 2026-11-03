"""Overlay state orchestration for DaVinci wheel controls."""

import time

from .area_target_helpers import area_key
from .config import WHEEL_DIAMETER_STATE_SECONDS
from .wheel_anchor_reuse_policy import wheel_anchor_is_reusable
from .wheel_manual_overlay_controller import (
    restore_manual_wheel_drag_overlay,
    show_manual_wheel_drag_overlay,
)
from .wheel_overlay_state_context import (
    ensure_wheel_handle_for_overlay,
    refresh_existing_hover_overlay,
    refresh_wheel_overlay_state,
    wheel_overlay_state,
)
from .wheel_overlay_visibility import (
    clear_hover_overlays,
    hide_inactive_overlays,
    set_wheel_dot_hidden,
)
from .wheel_state_accessors import (
    wheel_anchor_state,
    wheel_diameter_state,
)


def show_hover_overlay(
    manager,
    area,
    key,
    overlay_factory,
    detect_handle_raw_for_area_fn,
    debug_slow_fn=None,
):
    if not area or not key:
        hide_inactive_overlays(manager)
        manager._hover_visible_key = None
        return False

    hide_inactive_overlays(manager, key)
    now = time.time()
    anchor = wheel_anchor_state(manager)
    anchor_active = (
        anchor
        and wheel_anchor_is_reusable(anchor, key, now, area)
    )
    diameter = wheel_diameter_state(manager)
    diameter_active = (
        diameter
        and diameter.get('target_key') == key
        and now - diameter.get('updated_at', 0) <= WHEEL_DIAMETER_STATE_SECONDS
    )
    if not anchor_active and not diameter_active:
        ensure_wheel_handle_for_overlay(
            manager,
            area,
            detect_handle_raw_for_area_fn,
            debug_slow_fn=debug_slow_fn,
        )

    overlay = manager.overlays.get(key)
    if not overlay:
        overlay = overlay_factory(area)
        manager.overlays[key] = overlay
    overlay.update_area(area)
    overlay.update_wheel_state(wheel_overlay_state(manager, area))
    overlay.set_wheel_dot_hidden(False)
    overlay.set_hovered(True)
    overlay.show()
    manager._hover_visible_key = key
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0
    return True


def sync_wheel_overlays(manager):
    active_keys = set()

    for area in manager.areas:
        key = area_key(area)
        if not key:
            continue

        active_keys.add(key)
        overlay = manager.overlays.get(key)
        if overlay:
            overlay.update_area(area)
            overlay.update_wheel_state(wheel_overlay_state(manager, area))

    for key in list(manager.overlays.keys()):
        if key not in active_keys:
            overlay = manager.overlays.pop(key)
            overlay.set_wheel_dot_hidden(False)
            overlay.hide()
            overlay.deleteLater()
            if manager._hover_visible_key == key:
                manager._hover_visible_key = None

    active_key = area_key(manager.current_hover_area) if manager.current_hover_area else None
    hide_inactive_overlays(manager, active_key)


__all__ = [
    'clear_hover_overlays',
    'ensure_wheel_handle_for_overlay',
    'hide_inactive_overlays',
    'refresh_existing_hover_overlay',
    'refresh_wheel_overlay_state',
    'restore_manual_wheel_drag_overlay',
    'set_wheel_dot_hidden',
    'show_manual_wheel_drag_overlay',
    'show_hover_overlay',
    'sync_wheel_overlays',
    'wheel_overlay_state',
]
