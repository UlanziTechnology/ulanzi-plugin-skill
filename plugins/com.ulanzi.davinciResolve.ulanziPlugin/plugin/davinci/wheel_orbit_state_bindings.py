"""State service for closed-loop wheel orbit gestures."""

from .wheel_state_accessors import wheel_orbit_state as _wheel_orbit_state
from .wheel_state_handle_commits import (
    commit_wheel_predicted_handle as _commit_wheel_predicted_handle,
)
from .wheel_state_orbit_commit import (
    commit_wheel_orbit_feedback_state as _commit_wheel_orbit_feedback_state,
    start_wheel_orbit_session as _start_wheel_orbit_session,
    update_wheel_orbit_motion as _update_wheel_orbit_motion,
)


class WheelOrbitStateBindings:
    _LEGACY_CALLBACKS = {
        'commit_wheel_orbit_feedback_state_fn': 'commit_wheel_orbit_feedback_state',
        'commit_wheel_predicted_handle_fn': 'commit_wheel_predicted_handle',
        'start_wheel_orbit_session_fn': 'start_wheel_orbit_session',
        'update_wheel_orbit_motion_fn': 'update_wheel_orbit_motion',
        'wheel_orbit_state_fn': 'wheel_orbit_state',
    }

    def __init__(self, manager):
        self.manager = manager

    def __getitem__(self, name):
        try:
            method_name = self._LEGACY_CALLBACKS[name]
        except KeyError:
            raise KeyError(name) from None
        return getattr(self, method_name)

    def commit_wheel_orbit_feedback_state(self, *args, **kwargs):
        return _commit_wheel_orbit_feedback_state(
            self.manager,
            *args,
            **kwargs,
        )

    def commit_wheel_predicted_handle(self, *args, **kwargs):
        return _commit_wheel_predicted_handle(self.manager, *args, **kwargs)

    def start_wheel_orbit_session(self, *args, **kwargs):
        return _start_wheel_orbit_session(self.manager, *args, **kwargs)

    def update_wheel_orbit_motion(self, *args, **kwargs):
        return _update_wheel_orbit_motion(self.manager, *args, **kwargs)

    def wheel_orbit_state(self):
        return _wheel_orbit_state(self.manager)


def wheel_orbit_state_bindings(manager):
    return WheelOrbitStateBindings(manager)


wheel_orbit_state_callbacks = wheel_orbit_state_bindings


__all__ = [
    'WheelOrbitStateBindings',
    'wheel_orbit_state_bindings',
    'wheel_orbit_state_callbacks',
]
