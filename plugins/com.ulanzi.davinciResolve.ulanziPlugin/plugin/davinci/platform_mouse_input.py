"""Platform mouse input adapter for DaVinci wheel control."""

import math
import time

from .config import (
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_DOWN_SECONDS,
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_DISTANCE_PX,
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_ENABLED,
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_MICRO_DRAG_PX,
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_NEAR_MISS_SECONDS,
    WHEEL_MOUSE_DOUBLE_CLICK_GUARD_SECONDS,
)


class PlatformMouseInput:
    def __init__(
        self,
        *,
        is_windows,
        is_mac,
        davinci_available,
        win32_available,
        user32=None,
        ctypes_module=None,
        point_cls=None,
        nsevent=None,
        nsscreen=None,
        cg_event_create=None,
        cg_event_get_location=None,
        cg_event_create_mouse_event=None,
        cg_event_post=None,
        k_cg_hid_event_tap=None,
        k_mouse_moved=None,
        k_left_down=None,
        k_left_up=None,
        k_left_dragged=None,
        tourbox_mouse_input_cls=None,
        input_cls=None,
        mouseinput_cls=None,
        input_mouse=0,
        move_flag=0,
        left_down_flag=0,
        left_up_flag=0,
        absolute_flag=0,
        virtual_desktop_flag=0,
        mark_button_down_fn=None,
        mark_button_up_fn=None,
        default_extra_info=None,
    ):
        self.is_windows = is_windows
        self.is_mac = is_mac
        self.davinci_available = davinci_available
        self.win32_available = win32_available
        self.user32 = user32
        self.ctypes = ctypes_module
        self.point_cls = point_cls
        self.nsevent = nsevent
        self.nsscreen = nsscreen
        self.cg_event_create = cg_event_create
        self.cg_event_get_location = cg_event_get_location
        self.cg_event_create_mouse_event = cg_event_create_mouse_event
        self.cg_event_post = cg_event_post
        self.k_cg_hid_event_tap = k_cg_hid_event_tap
        self.k_mouse_moved = k_mouse_moved
        self.k_left_down = k_left_down
        self.k_left_up = k_left_up
        self.k_left_dragged = k_left_dragged
        self.tourbox_mouse_input_cls = tourbox_mouse_input_cls
        self.input_cls = input_cls
        self.mouseinput_cls = mouseinput_cls
        self.input_mouse = input_mouse
        self.move_flag = move_flag
        self.left_down_flag = left_down_flag
        self.left_up_flag = left_up_flag
        self.absolute_flag = absolute_flag
        self.virtual_desktop_flag = virtual_desktop_flag
        self.mark_button_down_fn = mark_button_down_fn or (lambda: None)
        self.mark_button_up_fn = mark_button_up_fn or (lambda: None)
        self.default_extra_info = default_extra_info
        self._last_left_up_at = 0.0
        self._last_left_up_pos = None
        self._last_left_down_at = 0.0
        self._last_left_down_pos = None
        self._last_left_drag_distance = None
        self._last_double_click_guard_log_at = 0.0
        self._last_double_click_guard_near_miss_log_at = 0.0
        self._mouse_button_down = False

    def _remember_left_down(self, x, y):
        self._last_left_down_at = time.monotonic()
        self._last_left_down_pos = (float(x), float(y))
        self._last_left_drag_distance = None

    def _remember_left_up(self, x, y):
        self._last_left_up_at = time.monotonic()
        self._last_left_up_pos = (float(x), float(y))
        if self._last_left_down_pos:
            down_x, down_y = self._last_left_down_pos
            self._last_left_drag_distance = math.hypot(float(x) - down_x, float(y) - down_y)

    def _should_suppress_rapid_repress(self, x, y, allow_rapid_repeat=False):
        if (
            allow_rapid_repeat
            or not WHEEL_MOUSE_DOUBLE_CLICK_GUARD_ENABLED
        ):
            return False

        now = time.monotonic()
        last_drag_is_micro = (
            self._last_left_drag_distance is not None
            and self._last_left_drag_distance <= WHEEL_MOUSE_DOUBLE_CLICK_GUARD_MICRO_DRAG_PX
        )
        if self._last_left_down_pos:
            down_elapsed = now - self._last_left_down_at
            last_down_x, last_down_y = self._last_left_down_pos
            down_distance = math.hypot(
                float(x) - last_down_x,
                float(y) - last_down_y,
            )
            if (
                0 <= down_elapsed <= WHEEL_MOUSE_DOUBLE_CLICK_GUARD_DOWN_SECONDS
                and down_distance <= WHEEL_MOUSE_DOUBLE_CLICK_GUARD_DISTANCE_PX
                and last_drag_is_micro
            ):
                if now - self._last_double_click_guard_log_at > 0.12:
                    print(
                        "mouse double-click guard suppressed drag begin: "
                        f"source=down-repeat "
                        f"dt={down_elapsed * 1000:.0f}ms "
                        f"distance={down_distance:.1f} "
                        f"drag={self._last_left_drag_distance:.1f} "
                        f"point=({float(x):.0f},{float(y):.0f}) "
                        f"last_down=({last_down_x:.0f},{last_down_y:.0f})"
                    )
                    self._last_double_click_guard_log_at = now
                return True

        if not self._last_left_up_pos or not last_drag_is_micro:
            return False

        elapsed = now - self._last_left_up_at
        if elapsed < 0:
            return False

        last_x, last_y = self._last_left_up_pos
        distance = math.hypot(float(x) - last_x, float(y) - last_y)
        if distance > WHEEL_MOUSE_DOUBLE_CLICK_GUARD_DISTANCE_PX:
            return False

        if elapsed > WHEEL_MOUSE_DOUBLE_CLICK_GUARD_SECONDS:
            if (
                elapsed <= WHEEL_MOUSE_DOUBLE_CLICK_GUARD_NEAR_MISS_SECONDS
                and now - self._last_double_click_guard_near_miss_log_at > 0.50
            ):
                print(
                    "mouse double-click guard near miss: "
                    f"dt={elapsed * 1000:.0f}ms "
                    f"limit={WHEEL_MOUSE_DOUBLE_CLICK_GUARD_SECONDS * 1000:.0f}ms "
                    f"distance={distance:.1f} "
                    f"point=({float(x):.0f},{float(y):.0f}) "
                    f"last=({last_x:.0f},{last_y:.0f})"
                )
                self._last_double_click_guard_near_miss_log_at = now
            return False

        if now - self._last_double_click_guard_log_at > 0.12:
            print(
                "mouse double-click guard suppressed drag begin: "
                f"source=up-repeat "
                f"dt={elapsed * 1000:.0f}ms "
                f"distance={distance:.1f} "
                f"point=({float(x):.0f},{float(y):.0f}) "
                f"last=({last_x:.0f},{last_y:.0f})"
            )
            self._last_double_click_guard_log_at = now
        return True

    def get_cursor_position(self):
        if self.is_windows and self.win32_available and self.user32 and self.point_cls:
            point = self.point_cls()
            if self.user32.GetCursorPos(self.ctypes.byref(point)):
                return (point.x, point.y)
            return (0, 0)

        if not self.is_mac or not self.davinci_available:
            return (0, 0)

        if self.cg_event_create and self.cg_event_get_location:
            event = self.cg_event_create(None)
            if event:
                loc = self.cg_event_get_location(event)
                return (loc.x, loc.y)

        if not self.nsevent or not self.nsscreen:
            return (0, 0)
        loc = self.nsevent.mouseLocation()
        screens = list(self.nsscreen.screens())
        if not screens:
            return (loc.x, -loc.y)
        primary_frame = screens[0].frame()
        primary_top = primary_frame.origin.y + primary_frame.size.height
        return (loc.x, primary_top - loc.y)

    def get_screen_bounds(self, margin=0):
        if self.is_windows and self.win32_available and self.user32:
            left = self.user32.GetSystemMetrics(76)
            top = self.user32.GetSystemMetrics(77)
            width = self.user32.GetSystemMetrics(78)
            height = self.user32.GetSystemMetrics(79)
            if width <= 0 or height <= 0:
                left = 0
                top = 0
                width = self.user32.GetSystemMetrics(0)
                height = self.user32.GetSystemMetrics(1)
            return (
                left + margin,
                top + margin,
                left + width - 1 - margin,
                top + height - 1 - margin,
            )

        if self.is_mac and self.nsscreen:
            screens = list(self.nsscreen.screens())
            if screens:
                primary_frame = screens[0].frame()
                primary_top = primary_frame.origin.y + primary_frame.size.height
                bounds = []
                for screen in screens:
                    frame = screen.frame()
                    left = float(frame.origin.x)
                    top = float(primary_top - (frame.origin.y + frame.size.height))
                    bounds.append((left, top, left + frame.size.width, top + frame.size.height))
                return (
                    min(item[0] for item in bounds) + margin,
                    min(item[1] for item in bounds) + margin,
                    max(item[2] for item in bounds) - 1 - margin,
                    max(item[3] for item in bounds) - 1 - margin,
                )

        return (-10**9, -10**9, 10**9, 10**9)

    def point_in_screen_bounds(self, x, y, margin=0):
        left, top, right, bottom = self.get_screen_bounds(margin)
        return left <= x <= right and top <= y <= bottom

    def tourbox_mouse_input_adapter(self):
        if not (
            self.is_windows
            and self.win32_available
            and self.tourbox_mouse_input_cls
            and self.user32
            and self.ctypes
            and self.input_cls
            and self.mouseinput_cls
        ):
            return None
        return self.tourbox_mouse_input_cls(
            is_available_fn=lambda: self.is_windows and self.win32_available,
            user32=self.user32,
            ctypes_module=self.ctypes,
            input_cls=self.input_cls,
            mouseinput_cls=self.mouseinput_cls,
            input_mouse=self.input_mouse,
            move_flag=self.move_flag,
            left_down_flag=self.left_down_flag,
            left_up_flag=self.left_up_flag,
            absolute_flag=self.absolute_flag,
            virtual_desktop_flag=self.virtual_desktop_flag,
            get_screen_bounds_fn=self.get_screen_bounds,
            mark_button_down_fn=self.mark_button_down_fn,
            mark_button_up_fn=self.mark_button_up_fn,
            default_extra_info=self.default_extra_info,
        )

    def send_mouse_input(self, flags, dx=0, dy=0, mouse_data=0, extra_info=None):
        adapter = self.tourbox_mouse_input_adapter()
        return bool(
            adapter
            and adapter.send_mouse_input(
                flags,
                dx=dx,
                dy=dy,
                mouse_data=mouse_data,
                extra_info=self.default_extra_info if extra_info is None else extra_info,
            )
        )

    def send_absolute_move(self, x, y, extra_info=None):
        adapter = self.tourbox_mouse_input_adapter()
        if not adapter and self.is_mac:
            return self.set_cursor_position(x, y)
        return bool(
            adapter
            and adapter.send_absolute_move(
                x,
                y,
                extra_info=self.default_extra_info if extra_info is None else extra_info,
            )
        )

    def send_relative_move(self, dx, dy, extra_info=None):
        adapter = self.tourbox_mouse_input_adapter()
        if not adapter and self.is_mac:
            current_x, current_y = self.get_cursor_position()
            return self.set_cursor_position(current_x + dx, current_y + dy)
        return bool(
            adapter
            and adapter.send_relative_move(
                dx,
                dy,
                extra_info=self.default_extra_info if extra_info is None else extra_info,
            )
        )

    def send_left_down(self, extra_info=None):
        adapter = self.tourbox_mouse_input_adapter()
        if not adapter and self.is_mac:
            x, y = self.get_cursor_position()
            return self.mouse_drag_begin(x, y, allow_rapid_repeat=True)
        return bool(
            adapter
            and adapter.send_left_down(
                extra_info=self.default_extra_info if extra_info is None else extra_info,
            )
        )

    def send_left_up(self, extra_info=None):
        adapter = self.tourbox_mouse_input_adapter()
        if not adapter and self.is_mac:
            x, y = self.get_cursor_position()
            return self.mouse_drag_end(x, y, pre_delay=0.0, post_delay=0.0)
        return bool(
            adapter
            and adapter.send_left_up(
                extra_info=self.default_extra_info if extra_info is None else extra_info,
            )
        )

    def mouse_drag_begin(self, x, y, allow_rapid_repeat=False):
        if self._should_suppress_rapid_repress(
            x,
            y,
            allow_rapid_repeat=allow_rapid_repeat,
        ):
            return False

        if self.is_windows and self.win32_available and self.user32:
            self.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.03)
            self.mark_button_down_fn()
            self._mouse_button_down = True
            self.user32.mouse_event(self.left_down_flag, 0, 0, 0, 0)
            self._remember_left_down(x, y)
            time.sleep(0.02)
            return True

        if self.is_mac and self.davinci_available and self.cg_event_create_mouse_event:
            self.set_cursor_position(x, y)
            down_event = self.cg_event_create_mouse_event(
                None, self.k_left_down, (int(x), int(y)), 0
            )
            if down_event:
                self.mark_button_down_fn()
                self._mouse_button_down = True
                self.cg_event_post(self.k_cg_hid_event_tap, down_event)
                self._remember_left_down(x, y)
                return True
        return False

    def mouse_drag_move(self, x, y):
        if self.is_windows and self.win32_available and self.user32:
            current_x, current_y = self.get_cursor_position()
            dx = int(round(x - current_x))
            dy = int(round(y - current_y))
            if dx or dy:
                self.user32.mouse_event(self.move_flag, dx, dy, 0, None)
            return True

        if self.is_mac and self.davinci_available and self.cg_event_create_mouse_event:
            drag_event = self.cg_event_create_mouse_event(
                None, self.k_left_dragged, (int(x), int(y)), 0
            )
            if drag_event:
                self.cg_event_post(self.k_cg_hid_event_tap, drag_event)
                return True
        return False

    def mouse_drag_move_absolute(self, x, y):
        if self.is_windows and self.win32_available and self.user32:
            self.user32.SetCursorPos(int(round(x)), int(round(y)))
            return True

        return self.mouse_drag_move(x, y)

    def mouse_drag_move_by(self, dx, dy=0):
        if self.is_windows and self.win32_available and self.user32:
            self.user32.mouse_event(self.move_flag, int(round(dx)), int(round(dy)), 0, None)
            return True
        if self.is_mac and self.davinci_available:
            current_x, current_y = self.get_cursor_position()
            return self.mouse_drag_move(current_x + dx, current_y + dy)
        return False

    def set_cursor_position(self, x, y):
        if self.is_windows and self.win32_available and self.user32:
            return bool(self.user32.SetCursorPos(int(round(x)), int(round(y))))

        if not (
            self.is_mac
            and self.davinci_available
            and self.cg_event_create_mouse_event
            and self.cg_event_post
        ):
            return False

        event_type = self.k_left_dragged if self._mouse_button_down else self.k_mouse_moved
        if event_type is None:
            return False
        event = self.cg_event_create_mouse_event(
            None,
            event_type,
            (int(round(x)), int(round(y))),
            0,
        )
        if not event:
            return False
        self.cg_event_post(self.k_cg_hid_event_tap, event)
        return True

    def mouse_drag_end(self, x, y, pre_delay=0.03, post_delay=0.03):
        if self.is_windows and self.win32_available and self.user32:
            if pre_delay > 0:
                time.sleep(pre_delay)
            try:
                self.user32.mouse_event(self.left_up_flag, 0, 0, 0, 0)
            finally:
                self._mouse_button_down = False
                self.mark_button_up_fn()
                self._remember_left_up(x, y)
            if post_delay > 0:
                time.sleep(post_delay)
            return True

        if self.is_mac and self.davinci_available and self.cg_event_create_mouse_event:
            if pre_delay > 0:
                time.sleep(pre_delay)
            posted = False
            try:
                up_event = self.cg_event_create_mouse_event(
                    None, self.k_left_up, (int(x), int(y)), 0
                )
                if up_event:
                    self.cg_event_post(self.k_cg_hid_event_tap, up_event)
                    posted = True
            finally:
                self._mouse_button_down = False
                self.mark_button_up_fn()
                self._remember_left_up(x, y)
            if posted and post_delay > 0:
                time.sleep(post_delay)
            return posted
        return False

    def mouse_click(self, x, y, allow_rapid_repeat=False):
        if not self.mouse_drag_begin(
            x,
            y,
            allow_rapid_repeat=allow_rapid_repeat,
        ):
            return False
        return self.mouse_drag_end(x, y)

    def simulate_mouse_drag(self, start_x, start_y, end_x, end_y, duration=0.2):
        if self.is_windows and self.win32_available and self.user32:
            start_x, start_y = int(start_x), int(start_y)
            end_x, end_y = int(end_x), int(end_y)
            self.user32.SetCursorPos(start_x, start_y)
            time.sleep(0.03)
            self.mark_button_down_fn()
            self.user32.mouse_event(self.left_down_flag, 0, 0, 0, 0)
            self._remember_left_down(start_x, start_y)
            time.sleep(0.02)

            try:
                steps = max(4, int(duration / 0.015))
                for step in range(1, steps + 1):
                    t = step / steps
                    x = int(start_x + (end_x - start_x) * t)
                    y = int(start_y + (end_y - start_y) * t)
                    self.user32.SetCursorPos(x, y)
                    time.sleep(duration / steps)

                time.sleep(0.03)
                self.user32.mouse_event(self.left_up_flag, 0, 0, 0, 0)
            finally:
                self.mark_button_up_fn()
                self._remember_left_up(end_x, end_y)
            time.sleep(0.03)
            return

        if not self.is_mac or not self.davinci_available or not self.cg_event_create_mouse_event:
            return

        if not self.mouse_drag_begin(start_x, start_y):
            return
        try:
            steps = max(4, int(duration / 0.015))
            for step in range(1, steps + 1):
                t = step / steps
                x = start_x + (end_x - start_x) * t
                y = start_y + (end_y - start_y) * t
                self.mouse_drag_move(x, y)
                time.sleep(duration / steps)
        finally:
            self.mouse_drag_end(end_x, end_y)

    def simulate_mouse_drag_path(self, points, duration=0.2):
        if not points:
            return
        if len(points) == 1:
            x, y = points[0]
            self.simulate_mouse_drag(x, y, x, y, duration=duration)
            return

        normalized = [(int(round(x)), int(round(y))) for x, y in points]
        start_x, start_y = normalized[0]
        end_x, end_y = normalized[-1]

        if self.is_windows and self.win32_available and self.user32:
            self.user32.SetCursorPos(start_x, start_y)
            time.sleep(0.03)
            self.mark_button_down_fn()
            self.user32.mouse_event(self.left_down_flag, 0, 0, 0, 0)
            self._remember_left_down(start_x, start_y)
            time.sleep(0.02)

            try:
                delay = duration / max(1, len(normalized) - 1)
                for x, y in normalized[1:]:
                    self.user32.SetCursorPos(x, y)
                    time.sleep(delay)

                time.sleep(0.03)
                self.user32.mouse_event(self.left_up_flag, 0, 0, 0, 0)
            finally:
                self.mark_button_up_fn()
                self._remember_left_up(end_x, end_y)
            time.sleep(0.03)
            return

        if not self.is_mac or not self.davinci_available or not self.cg_event_create_mouse_event:
            return

        if not self.mouse_drag_begin(start_x, start_y):
            return
        try:
            delay = duration / max(1, len(normalized) - 1)
            for x, y in normalized[1:]:
                self.mouse_drag_move(x, y)
                time.sleep(delay)
        finally:
            self.mouse_drag_end(end_x, end_y)
