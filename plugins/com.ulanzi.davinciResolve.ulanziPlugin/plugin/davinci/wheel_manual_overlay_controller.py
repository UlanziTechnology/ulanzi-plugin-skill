"""Manual wheel-drag overlay display helpers."""

from .wheel_overlay_state_context import wheel_overlay_state
from .wheel_overlay_visibility import hide_inactive_overlays


def show_manual_wheel_drag_overlay(manager, area, key, overlay_factory):
    hide_inactive_overlays(manager, key)
    overlay = manager.overlays.get(key)
    if not overlay:
        overlay = overlay_factory(area)
        manager.overlays[key] = overlay
    overlay.update_area(area)
    overlay.update_wheel_state(wheel_overlay_state(manager, area))
    overlay.set_hovered(True)
    overlay.set_wheel_dot_hidden(True)
    overlay.show()
    manager._hover_visible_key = key
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0
    return True


def restore_manual_wheel_drag_overlay(manager, area, key):
    hide_inactive_overlays(manager, key)
    overlay = manager.overlays.get(key)
    if overlay:
        overlay.update_area(area)
        overlay.update_wheel_state(wheel_overlay_state(manager, area))
        overlay.set_wheel_dot_hidden(False)
        overlay.set_hovered(True)
        overlay.show()
        manager._hover_visible_key = key
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0
    return bool(overlay)


__all__ = [
    'restore_manual_wheel_drag_overlay',
    'show_manual_wheel_drag_overlay',
]
