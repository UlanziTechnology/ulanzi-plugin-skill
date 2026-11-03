"""State service for outer-anchor wheel rotation."""

from .wheel_overlay_state_context import wheel_overlay_state as _wheel_overlay_state
from .wheel_state_accessors import (
    clear_wheel_anchor_state as _clear_wheel_anchor_state,
    clear_wheel_diameter_state as _clear_wheel_diameter_state,
    wheel_anchor_state as _wheel_anchor_state,
    wheel_diameter_state as _wheel_diameter_state,
    wheel_handle_for_area as _wheel_handle_for_area,
    wheel_state_for_area as _wheel_state_for_area,
)
from .wheel_state_anchor_commit import (
    commit_wheel_anchor_state as _commit_wheel_anchor_state,
    seed_wheel_anchor_state_from_overlay as _seed_wheel_anchor_state_from_overlay,
)


class WheelOuterAnchorStateBindings:
    _LEGACY_CALLBACKS = {
        'clear_wheel_anchor_state_fn': 'clear_wheel_anchor_state',
        'clear_wheel_diameter_state_fn': 'clear_wheel_diameter_state',
        'commit_wheel_anchor_state_fn': 'commit_wheel_anchor_state',
        'overlay_state_fn': 'overlay_state',
        'seed_wheel_anchor_state_from_overlay_fn': 'seed_wheel_anchor_state_from_overlay',
        'wheel_anchor_state_fn': 'wheel_anchor_state',
        'wheel_diameter_state_fn': 'wheel_diameter_state',
        'wheel_handle_for_area_fn': 'wheel_handle_for_area',
        'wheel_state_for_area_fn': 'wheel_state_for_area',
    }

    def __init__(self, manager):
        self.manager = manager

    def __getitem__(self, name):
        try:
            method_name = self._LEGACY_CALLBACKS[name]
        except KeyError:
            raise KeyError(name) from None
        return getattr(self, method_name)

    def clear_wheel_anchor_state(self):
        return _clear_wheel_anchor_state(self.manager)

    def clear_wheel_diameter_state(self):
        return _clear_wheel_diameter_state(self.manager)

    def commit_wheel_anchor_state(self, *args, **kwargs):
        return _commit_wheel_anchor_state(self.manager, *args, **kwargs)

    def overlay_state(self, area):
        return _wheel_overlay_state(self.manager, area)

    def seed_wheel_anchor_state_from_overlay(self, area, **kwargs):
        return _seed_wheel_anchor_state_from_overlay(
            self.manager,
            area,
            **kwargs,
        )

    def wheel_anchor_state(self):
        return _wheel_anchor_state(self.manager)

    def wheel_diameter_state(self):
        return _wheel_diameter_state(self.manager)

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


def wheel_outer_anchor_state_bindings(manager):
    return WheelOuterAnchorStateBindings(manager)


wheel_outer_anchor_state_callbacks = wheel_outer_anchor_state_bindings


__all__ = [
    'WheelOuterAnchorStateBindings',
    'wheel_outer_anchor_state_bindings',
    'wheel_outer_anchor_state_callbacks',
]
