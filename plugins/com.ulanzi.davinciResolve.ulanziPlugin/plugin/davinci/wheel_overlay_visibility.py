"""Basic overlay visibility helpers for wheel controls."""

from .area_target_helpers import area_key


def set_wheel_dot_hidden(manager, area, hidden):
    if not area:
        return False

    overlay = manager.overlays.get(area_key(area))
    if not overlay:
        return False

    overlay.set_wheel_dot_hidden(hidden)
    return True


def hide_inactive_overlays(manager, active_key=None):
    for key, overlay in manager.overlays.items():
        if active_key is not None and key == active_key:
            continue
        overlay.set_wheel_dot_hidden(False)
        overlay.set_hovered(False)
        overlay.hide()
        if manager._hover_visible_key == key:
            manager._hover_visible_key = None


def clear_hover_overlays(manager):
    for overlay in manager.overlays.values():
        overlay.set_wheel_dot_hidden(False)
        overlay.set_hovered(False)
        overlay.hide()
    manager._hover_visible_key = None
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0


__all__ = [
    'clear_hover_overlays',
    'hide_inactive_overlays',
    'set_wheel_dot_hidden',
]
