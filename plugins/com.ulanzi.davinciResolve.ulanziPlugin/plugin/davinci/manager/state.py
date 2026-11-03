"""Manager-owned state adapters for interaction controllers."""

from ..wheel_state_detection_commits import store_wheel_handle_from_detection
from ..wheel_state_accessors import (
    clear_wheel_control_state,
    clear_wheel_diameter_state,
    mark_recent_wheel_area,
    set_wheel_drag_state,
    set_wheel_orbit_state,
    wheel_drag_state,
    wheel_handle_for_area,
    wheel_orbit_state,
    wheel_segment_state,
)
from ..wheel_state_handle_commits import (
    commit_wheel_detected_handle,
    commit_wheel_predicted_handle,
    commit_wheel_raw_handle,
)
from ..wheel_state_orbit_commit import commit_wheel_segment_state
from ..wheel_state_reset_commit import commit_wheel_center_reset_state


def wheel_release_state_callbacks(manager):
    return {
        'wheel_drag_state_fn': lambda: wheel_drag_state(manager),
        'clear_wheel_drag_state_fn': lambda: set_wheel_drag_state(manager, None),
        'wheel_orbit_state_fn': lambda: wheel_orbit_state(manager),
        'clear_wheel_orbit_state_fn': lambda: set_wheel_orbit_state(manager, None),
    }


def wheel_handle_detection_state_callbacks(manager):
    return {
        'areas_fn': lambda: manager.areas,
        'commit_wheel_detected_handle_fn': (
            lambda *args, **kwargs: commit_wheel_detected_handle(
                manager,
                *args,
                **kwargs,
            )
        ),
        'wheel_handle_for_area_fn': (
            lambda area_name, default=None: wheel_handle_for_area(manager, area_name, default)
        ),
    }


def wheel_reset_state_callbacks(manager):
    return {
        'commit_wheel_center_reset_state_fn': (
            lambda *args, **kwargs: commit_wheel_center_reset_state(
                manager,
                *args,
                **kwargs,
            )
        ),
        'current_hover_area_fn': lambda: manager.current_hover_area,
        'wheel_drag_state_fn': lambda: wheel_drag_state(manager),
        'wheel_handle_for_area_fn': (
            lambda area_name, default=None: wheel_handle_for_area(manager, area_name, default)
        ),
    }


def wheel_legacy_state_callbacks(manager):
    return {
        'clear_wheel_diameter_state_fn': lambda: clear_wheel_diameter_state(manager),
        'commit_wheel_predicted_handle_fn': (
            lambda *args, **kwargs: commit_wheel_predicted_handle(
                manager,
                *args,
                **kwargs,
            )
        ),
        'commit_wheel_raw_handle_fn': (
            lambda *args, **kwargs: commit_wheel_raw_handle(manager, *args, **kwargs)
        ),
        'commit_wheel_segment_state_fn': (
            lambda *args, **kwargs: commit_wheel_segment_state(manager, *args, **kwargs)
        ),
        'wheel_handle_for_area_fn': (
            lambda area_name, default=None: wheel_handle_for_area(manager, area_name, default)
        ),
        'wheel_segment_state_fn': lambda: wheel_segment_state(manager),
    }


def wheel_manual_drag_state_callbacks(manager):
    return {
        'areas_fn': lambda: manager.areas,
        'clear_control_state_fn': lambda **kwargs: clear_wheel_control_state(manager, **kwargs),
        'clear_manual_drag_state_fn': lambda: _set_manual_drag_state(manager, None),
        'clear_pending_hover_overlay_fn': lambda: _clear_pending_hover_overlay(manager),
        'davinci_ready_flags_fn': lambda: bool(manager._davinci_running and manager._davinci_active),
        'manual_drag_state_fn': lambda: manager._manual_wheel_drag,
        'mark_recent_wheel_area_fn': lambda area: mark_recent_wheel_area(manager, area),
        'overlay_for_key_fn': lambda key: manager.overlays.get(key),
        'param_drag_state_fn': lambda: manager._param_drag,
        'set_current_hover_area_fn': lambda area: _set_current_hover_area(manager, area),
        'set_hover_visible_key_fn': lambda key: _set_hover_visible_key(manager, key),
        'set_manual_drag_state_fn': lambda drag: _set_manual_drag_state(manager, drag),
        'store_wheel_handle_from_detection_fn': (
            lambda area, handle, source='manual_release': store_wheel_handle_from_detection(
                manager,
                area,
                handle,
                source=source,
            )
        ),
        'wheel_drag_state_fn': lambda: wheel_drag_state(manager),
        'wheel_orbit_state_fn': lambda: wheel_orbit_state(manager),
    }


def _clear_pending_hover_overlay(manager):
    manager._pending_hover_overlay_key = None
    manager._pending_hover_overlay_at = 0.0


def _set_current_hover_area(manager, area):
    manager.current_hover_area = area
    return area


def _set_hover_visible_key(manager, key):
    manager._hover_visible_key = key
    return key


def _set_manual_drag_state(manager, drag):
    manager._manual_wheel_drag = drag
    return drag


__all__ = [
    'wheel_release_state_callbacks',
    'wheel_handle_detection_state_callbacks',
    'wheel_reset_state_callbacks',
    'wheel_legacy_state_callbacks',
    'wheel_manual_drag_state_callbacks',
]
