"""State for mouse buttons pressed by the plugin itself."""

import time


class PluginMouseButtonState:
    def __init__(self, time_fn=None):
        self._time_fn = time_fn or time.time
        self._depth = 0
        self._active_until = 0.0

    def mark_down(self):
        now = self._time_fn()
        self._depth += 1
        self._active_until = max(self._active_until, now + 1.0)

    def mark_up(self):
        now = self._time_fn()
        self._depth = max(0, self._depth - 1)
        self._active_until = max(self._active_until, now + 0.25)

    def active(self):
        return self._depth > 0 or self._time_fn() < self._active_until


def mark_plugin_mouse_button_down(state):
    state.mark_down()


def mark_plugin_mouse_button_up(state):
    state.mark_up()


def plugin_mouse_button_active(state):
    return state.active()


def is_left_mouse_button_down(
    *,
    is_windows,
    win32_available,
    user32,
    vk_lbutton,
    is_mac,
    davinci_available,
    nsevent,
):
    if is_windows and win32_available and user32 is not None:
        return bool(user32.GetAsyncKeyState(vk_lbutton) & 0x8000)
    if is_mac and davinci_available and nsevent is not None:
        try:
            return bool(nsevent.pressedMouseButtons() & 1)
        except Exception:
            return False
    return False


__all__ = [
    'PluginMouseButtonState',
    'is_left_mouse_button_down',
    'mark_plugin_mouse_button_down',
    'mark_plugin_mouse_button_up',
    'plugin_mouse_button_active',
]
