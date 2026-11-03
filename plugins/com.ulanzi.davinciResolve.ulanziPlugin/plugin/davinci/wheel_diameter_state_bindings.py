"""State service used by wheel diameter gestures."""

from .wheel_state_accessors import (
    clear_wheel_anchor_state as _clear_wheel_anchor_state,
    clear_wheel_diameter_state as _clear_wheel_diameter_state,
    mark_recent_wheel_area as _mark_recent_wheel_area,
    set_wheel_drag_state as _set_wheel_drag_state,
    wheel_anchor_state as _wheel_anchor_state,
    wheel_diameter_state as _wheel_diameter_state,
    wheel_drag_state as _wheel_drag_state,
    wheel_handle_for_area as _wheel_handle_for_area,
    wheel_state_for_area as _wheel_state_for_area,
)
from .wheel_state_axis_lock import (
    set_wheel_diameter_axis_lock as _set_wheel_diameter_axis_lock,
    wheel_diameter_axis_lock_for_manager_area as _wheel_diameter_axis_lock_for_area,
)
from .wheel_state_diameter_commit import (
    commit_wheel_diameter_state as _commit_wheel_diameter_state,
)
from .wheel_state_store_bridge import (
    commit_wheel_capability_to_store as _commit_wheel_capability_to_store,
    refresh_wheel_overlay_from_state_manager as _refresh_wheel_overlay,
)


class WheelDiameterStateBindings:
    """Expose manager state as named operations instead of a callback dictionary."""

    _LEGACY_CALLBACKS = {
        'commit_wheel_diameter_state_fn': 'commit_wheel_diameter_state',
        'commit_wheel_capability_to_store_fn': 'commit_wheel_capability_to_store',
        'clear_wheel_anchor_state_fn': 'clear_wheel_anchor_state',
        'clear_wheel_diameter_state_fn': 'clear_wheel_diameter_state',
        'clear_wheel_drag_state_fn': 'clear_wheel_drag_state',
        'wheel_anchor_state_fn': 'wheel_anchor_state',
        'wheel_diameter_state_fn': 'wheel_diameter_state',
        'wheel_drag_state_fn': 'wheel_drag_state',
        'wheel_handle_for_area_fn': 'wheel_handle_for_area',
        'wheel_state_for_area_fn': 'wheel_state_for_area',
        'set_wheel_drag_state_fn': 'set_wheel_drag_state',
        'set_wheel_diameter_axis_lock_fn': 'set_wheel_diameter_axis_lock',
        'wheel_diameter_axis_lock_for_area_fn': 'wheel_diameter_axis_lock_for_area',
        'mark_recent_wheel_area_fn': 'mark_recent_wheel_area',
        'refresh_wheel_overlay_fn': 'refresh_wheel_overlay',
    }

    def __init__(self, manager):
        self.manager = manager

    def __getitem__(self, name):
        try:
            method_name = self._LEGACY_CALLBACKS[name]
        except KeyError:
            raise KeyError(name) from None
        return getattr(self, method_name)

    def commit_wheel_diameter_state(self, *args, **kwargs):
        return _commit_wheel_diameter_state(self.manager, *args, **kwargs)

    def commit_wheel_capability_to_store(self, *args, **kwargs):
        return _commit_wheel_capability_to_store(self.manager, *args, **kwargs)

    def clear_wheel_anchor_state(self):
        return _clear_wheel_anchor_state(self.manager)

    def clear_wheel_diameter_state(self):
        return _clear_wheel_diameter_state(self.manager)

    def clear_wheel_drag_state(self):
        return _set_wheel_drag_state(self.manager, None)

    def wheel_anchor_state(self):
        return _wheel_anchor_state(self.manager)

    def wheel_diameter_state(self):
        return _wheel_diameter_state(self.manager)

    def wheel_drag_state(self):
        return _wheel_drag_state(self.manager)

    def wheel_handle_for_area(self, area_name, default=None):
        return _wheel_handle_for_area(self.manager, area_name, default)

    def wheel_state_for_area(self, area, center_x, center_y, wheel_radius):
        return _wheel_state_for_area(
            self.manager,
            area,
            center_x,
            center_y,
            wheel_radius,
        )

    def set_wheel_drag_state(self, drag):
        return _set_wheel_drag_state(self.manager, drag)

    def set_wheel_diameter_axis_lock(self, *args, **kwargs):
        return _set_wheel_diameter_axis_lock(self.manager, *args, **kwargs)

    def wheel_diameter_axis_lock_for_area(self, area, center_x, center_y):
        return _wheel_diameter_axis_lock_for_area(
            self.manager,
            area,
            center_x,
            center_y,
        )

    def mark_recent_wheel_area(self, *args, **kwargs):
        return _mark_recent_wheel_area(self.manager, *args, **kwargs)

    def refresh_wheel_overlay(self, area):
        return _refresh_wheel_overlay(self.manager, area)


def wheel_diameter_state_bindings(manager):
    return WheelDiameterStateBindings(manager)


wheel_diameter_state_callbacks = wheel_diameter_state_bindings


__all__ = [
    'WheelDiameterStateBindings',
    'wheel_diameter_state_bindings',
    'wheel_diameter_state_callbacks',
]
