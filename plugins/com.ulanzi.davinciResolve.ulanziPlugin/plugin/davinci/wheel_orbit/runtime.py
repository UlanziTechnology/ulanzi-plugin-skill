"""Typed dependencies for closed-loop wheel orbit gestures."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..wheel_orbit_state_bindings import WheelOrbitStateBindings


Callback = Callable[..., Any]


@dataclass(frozen=True)
class WheelOrbitRuntime:
    state: 'WheelOrbitStateBindings'
    mouse_drag_begin: Callback
    mouse_drag_move_path: Callback
    mouse_drag_move_by_path: Callback
    get_cursor_position: Callback
    detect_handle: Callback
    detect_raw_handle: Callback
    clear_wheel_orbit: Callback
    release_param_drag: Callback
    release_wheel_drag: Callback
    release_wheel_orbit_drag: Callback


__all__ = ['WheelOrbitRuntime']
