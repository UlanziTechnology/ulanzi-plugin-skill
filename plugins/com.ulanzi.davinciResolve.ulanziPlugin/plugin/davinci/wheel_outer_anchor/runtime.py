"""Typed dependencies for outer-anchor wheel gestures."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from ..wheel_outer_anchor_state_bindings import WheelOuterAnchorStateBindings


Callback = Callable[..., Any]


@dataclass(frozen=True)
class WheelOuterAnchorRuntime:
    state: 'WheelOuterAnchorStateBindings'
    detect_wheel_circle_in_area: Callback
    detect_handle: Callback
    detect_raw_handle: Callback
    mouse_drag_begin: Callback
    mouse_drag_move_absolute_path: Callback
    mouse_drag_end: Callback
    get_cursor_position: Callback
    clear_wheel_orbit: Callback
    release_param_drag: Callback
    release_wheel_drag: Callback
    set_cursor_position: Optional[Callback] = None
    pump_overlay_messages: Optional[Callback] = None
    debug_slow: Optional[Callback] = None


__all__ = ['WheelOuterAnchorRuntime']
