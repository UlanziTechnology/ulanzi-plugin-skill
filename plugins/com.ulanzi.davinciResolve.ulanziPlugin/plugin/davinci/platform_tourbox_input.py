"""Win32 SendInput adapter used by optional TourBox diagnostics."""


class TourBoxMouseInput:
    def __init__(
        self,
        *,
        is_available_fn,
        user32,
        ctypes_module,
        input_cls,
        mouseinput_cls,
        input_mouse,
        move_flag,
        left_down_flag,
        left_up_flag,
        absolute_flag,
        virtual_desktop_flag,
        get_screen_bounds_fn,
        mark_button_down_fn,
        mark_button_up_fn,
        default_extra_info,
    ):
        self._is_available_fn = is_available_fn
        self._user32 = user32
        self._ctypes = ctypes_module
        self._input_cls = input_cls
        self._mouseinput_cls = mouseinput_cls
        self._input_mouse = input_mouse
        self._move_flag = move_flag
        self._left_down_flag = left_down_flag
        self._left_up_flag = left_up_flag
        self._absolute_flag = absolute_flag
        self._virtual_desktop_flag = virtual_desktop_flag
        self._get_screen_bounds_fn = get_screen_bounds_fn
        self._mark_button_down_fn = mark_button_down_fn
        self._mark_button_up_fn = mark_button_up_fn
        self._default_extra_info = default_extra_info

    def _extra_info(self, extra_info):
        return self._default_extra_info if extra_info is None else extra_info

    def screen_point_to_absolute_input(self, x, y):
        left, top, right, bottom = self._get_screen_bounds_fn(0)
        width = max(1, right - left)
        height = max(1, bottom - top)
        abs_x = int(round((float(x) - left) * 65535.0 / width))
        abs_y = int(round((float(y) - top) * 65535.0 / height))
        return max(0, min(65535, abs_x)), max(0, min(65535, abs_y))

    def send_mouse_input(self, flags, dx=0, dy=0, mouse_data=0, extra_info=None):
        if not self._is_available_fn():
            return False

        entry = self._input_cls()
        entry.type = self._input_mouse
        entry.union.mi = self._mouseinput_cls(
            int(round(dx)),
            int(round(dy)),
            int(mouse_data),
            int(flags),
            0,
            int(self._extra_info(extra_info)),
        )
        sent = self._user32.SendInput(
            1,
            self._ctypes.byref(entry),
            self._ctypes.sizeof(self._input_cls),
        )
        return sent == 1

    def send_absolute_move(self, x, y, extra_info=None):
        abs_x, abs_y = self.screen_point_to_absolute_input(x, y)
        return self.send_mouse_input(
            self._move_flag | self._absolute_flag | self._virtual_desktop_flag,
            abs_x,
            abs_y,
            extra_info=extra_info,
        )

    def send_relative_move(self, dx, dy, extra_info=None):
        return self.send_mouse_input(
            self._move_flag,
            dx,
            dy,
            extra_info=extra_info,
        )

    def send_left_down(self, extra_info=None):
        self._mark_button_down_fn()
        return self.send_mouse_input(self._left_down_flag, extra_info=extra_info)

    def send_left_up(self, extra_info=None):
        try:
            return self.send_mouse_input(self._left_up_flag, extra_info=extra_info)
        finally:
            self._mark_button_up_fn()


__all__ = ['TourBoxMouseInput']
