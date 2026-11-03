"""Typed dependencies shared by the wheel diameter workflow."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from ..wheel_diameter_state_bindings import WheelDiameterStateBindings


Callback = Callable[..., Any]


@dataclass(frozen=True)
class DiameterPreparation:
    area_name: str
    target_key: str
    now: float


@dataclass(frozen=True)
class WheelDiameterRuntime:
    state: 'WheelDiameterStateBindings'
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
    pump_overlay_messages: Optional[Callback] = None
    debug_slow: Optional[Callback] = None


__all__ = ['DiameterPreparation', 'WheelDiameterRuntime']
