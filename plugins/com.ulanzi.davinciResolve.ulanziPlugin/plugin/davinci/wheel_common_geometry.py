"""Small shared geometry helpers for wheel controllers."""

import math


def build_linear_path(start_x, start_y, end_x, end_y, steps=4):
    points = []
    for step in range(1, max(1, steps) + 1):
        t = step / max(1, steps)
        points.append((
            start_x + (end_x - start_x) * t,
            start_y + (end_y - start_y) * t,
        ))
    return points


def normalize_angle_radians(angle):
    while angle <= -math.pi:
        angle += math.pi * 2
    while angle > math.pi:
        angle -= math.pi * 2
    return angle


__all__ = [
    'build_linear_path',
    'normalize_angle_radians',
]
