"""Cached DaVinci panel layouts keyed by window geometry and learned clicks."""

import copy
import math
import time


VIEW_PRIMARY_BARS = 'primary_bars'
VIEW_WHEEL_PREFIX = 'wheel_layout_'


def layout_geometry_key(frame, hwnd=0):
    if not frame:
        return None
    try:
        x, y, width, height = frame
        return (
            int(hwnd or 0),
            int(round(float(x))),
            int(round(float(y))),
            int(round(float(width))),
            int(round(float(height))),
        )
    except Exception:
        return None


def area_type_counts(areas):
    counts = {}
    for area in areas or []:
        area_type = area.get('type') or 'unknown'
        counts[area_type] = counts.get(area_type, 0) + 1
    return counts


def layout_profile(areas):
    counts = area_type_counts(areas)
    wheels = [
        area for area in areas or []
        if area.get('type') == 'wheel'
    ]
    wheel_points = []
    if wheels:
        left = min(float(area.get('center_x', area.get('x', 0))) for area in wheels)
        top = min(float(area.get('center_y', area.get('y', 0))) for area in wheels)
        for area in sorted(wheels, key=lambda item: (item.get('center_y', 0), item.get('center_x', 0))):
            center_x = float(area.get('center_x', area.get('x', 0)))
            center_y = float(area.get('center_y', area.get('y', 0)))
            width = float(area.get('w', 0))
            height = float(area.get('h', 0))
            wheel_points.append((
                int(round((center_x - left) / 4.0)),
                int(round((center_y - top) / 4.0)),
                int(round(width / 4.0)),
                int(round(height / 4.0)),
            ))
    return (
        len(areas or []),
        counts.get('wheel', 0),
        counts.get('vertical_slider', 0),
        counts.get('numeric', 0),
        counts.get('slider', 0),
        tuple(wheel_points),
    )


def is_bars_layout(areas):
    counts = area_type_counts(areas)
    return counts.get('vertical_slider', 0) >= 3


class LayoutCache:
    def __init__(self, *, clock=None, click_match_radius=34.0):
        self._clock = clock or time.time
        self._click_match_radius = float(click_match_radius)
        self._entries = {}
        self._clicks = {}

    def store_layout(self, geometry_key, areas):
        if not geometry_key or not areas:
            return None

        entries = self._entries.setdefault(geometry_key, {})
        profile = layout_profile(areas)
        view_key = self._view_key_for_profile(entries, areas, profile)
        entries[view_key] = {
            'areas': copy.deepcopy(list(areas)),
            'profile': profile,
            'updated_at': self._clock(),
        }
        return view_key

    def get_layout(self, geometry_key, view_key):
        entry = self._entries.get(geometry_key, {}).get(view_key)
        if not entry:
            return None
        return copy.deepcopy(entry['areas'])

    def remember_click(self, geometry_key, mouse_x, mouse_y, view_key):
        if not geometry_key or not view_key:
            return False

        click = {
            'x': float(mouse_x),
            'y': float(mouse_y),
            'view_key': view_key,
            'updated_at': self._clock(),
        }
        clicks = self._clicks.setdefault(geometry_key, [])
        filtered = []
        for existing in clicks:
            same_view = existing.get('view_key') == view_key
            distance = math.hypot(
                float(existing.get('x', 0.0)) - click['x'],
                float(existing.get('y', 0.0)) - click['y'],
            )
            if same_view and distance <= self._click_match_radius * 1.5:
                continue
            filtered.append(existing)
        filtered.append(click)
        self._clicks[geometry_key] = filtered[-12:]
        return True

    def view_for_click(self, geometry_key, mouse_x, mouse_y):
        best = None
        best_distance = None
        for click in self._clicks.get(geometry_key, []):
            distance = math.hypot(
                float(click.get('x', 0.0)) - float(mouse_x),
                float(click.get('y', 0.0)) - float(mouse_y),
            )
            if distance > self._click_match_radius:
                continue
            if best is None or distance < best_distance:
                best = click
                best_distance = distance
        return best.get('view_key') if best else None

    def cached_view_count(self, geometry_key):
        return len(self._entries.get(geometry_key, {}))

    def _view_key_for_profile(self, entries, areas, profile):
        if is_bars_layout(areas):
            return VIEW_PRIMARY_BARS

        for view_key, entry in entries.items():
            if view_key == VIEW_PRIMARY_BARS:
                continue
            if entry.get('profile') == profile:
                return view_key

        next_index = 1
        while f'{VIEW_WHEEL_PREFIX}{next_index}' in entries:
            next_index += 1
        return f'{VIEW_WHEEL_PREFIX}{next_index}'


__all__ = [
    'LayoutCache',
    'VIEW_PRIMARY_BARS',
    'VIEW_WHEEL_PREFIX',
    'area_type_counts',
    'is_bars_layout',
    'layout_geometry_key',
    'layout_profile',
]
