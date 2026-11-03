"""Bound mouse action callbacks for DaVinci controller code."""

from .platform_mouse_paths import (
    drag_move_absolute_path,
    drag_move_by_path,
    drag_move_path,
)


class PlatformMouseActions:
    """Adapts PlatformMouseInput methods into controller callback functions."""

    def __init__(self, mouse_input):
        self.mouse_input = mouse_input

    def mouse_drag_begin(self, x, y, allow_rapid_repeat=False):
        return self.mouse_input.mouse_drag_begin(
            x,
            y,
            allow_rapid_repeat=allow_rapid_repeat,
        )

    def mouse_drag_move(self, x, y):
        return self.mouse_input.mouse_drag_move(x, y)

    def mouse_drag_move_absolute(self, x, y):
        return self.mouse_input.mouse_drag_move_absolute(x, y)

    def mouse_drag_move_by(self, dx, dy=0):
        return self.mouse_input.mouse_drag_move_by(dx, dy)

    def mouse_drag_end(self, x, y, pre_delay=0.03, post_delay=0.03):
        return self.mouse_input.mouse_drag_end(
            x,
            y,
            pre_delay=pre_delay,
            post_delay=post_delay,
        )

    def mouse_click(self, x, y, allow_rapid_repeat=False):
        return self.mouse_input.mouse_click(
            x,
            y,
            allow_rapid_repeat=allow_rapid_repeat,
        )

    def mouse_drag_move_path(self, points, duration=0.035):
        return drag_move_path(points, self.mouse_drag_move, duration=duration)

    def mouse_drag_move_absolute_path(self, points, duration=0.035):
        return drag_move_absolute_path(
            points,
            self.mouse_drag_move_absolute,
            duration=duration,
        )

    def mouse_drag_move_by_path(
        self,
        total_dx,
        total_dy,
        steps=8,
        duration=0.035,
        max_step_px=None,
    ):
        return drag_move_by_path(
            total_dx,
            total_dy,
            self.mouse_drag_move_by,
            steps=steps,
            duration=duration,
            max_step_px=max_step_px,
        )


__all__ = ['PlatformMouseActions']
