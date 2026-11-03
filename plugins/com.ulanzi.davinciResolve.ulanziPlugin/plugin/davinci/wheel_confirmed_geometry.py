"""Keep measured wheel geometry for one unchanged accessibility layout.

Only complete scans publish a cache. Pixel-derived radii and numeric VALUES
are deliberately absent from its key. No pointer or native UI I/O lives here.
"""

import math
import threading


_FIELDS = ('wheel_center_x', 'wheel_center_y', 'visual_center_x',
           'visual_center_y', 'wheel_radius')


def _frame(value):
    try:
        result = tuple(float(v) for v in value)
        if len(result) == 4 and all(math.isfinite(v) for v in result):
            if result[2] > 0 and result[3] > 0:
                return result
    except (TypeError, ValueError):
        pass
    return None


def layout_geometry_context(window_frame, pid, hwnd, labels, numeric_inputs, sliders):
    """Return None when there is no reliable structural identity to reuse."""
    frame = _frame(window_frame)
    if frame is None or not pid:
        return None
    groups = []
    for items, named in ((labels, True), (numeric_inputs, False), (sliders, False)):
        group = []
        for item in items or []:
            item_frame = _frame(item.get('frame'))
            if item_frame is None:
                return None
            group.append((str(item.get('name', '')) if named else '', item_frame,
                          str(item.get('type', '')), str(item.get('role', '')),
                          str(item.get('orientation', ''))))
        groups.append(tuple(sorted(group)))
    if not groups[0] and not groups[1]:
        return None
    return (int(pid), int(hwnd or 0), frame, *groups)


def _area_bounds(area):
    return _frame(tuple(area.get(k) for k in ('x', 'y', 'w', 'h')))


def _geometry(value, area):
    if not value or not isinstance(value, dict):
        return None
    try:
        result = {k: float(value[k]) for k in _FIELDS}
        if not all(math.isfinite(v) for v in result.values()):
            return None
        bounds = _area_bounds(area)
        if bounds is None:
            return None
        x, y, w, h = bounds
        # Never freeze a fallback or a radius larger than the search region.
        if not 18 <= result['wheel_radius'] < min(w, h) * 0.52:
            return None
        if not (x <= result['wheel_center_x'] <= x + w
                and y <= result['wheel_center_y'] <= y + h):
            return None
        return result
    except (KeyError, TypeError, ValueError):
        return None


def confirmed_geometry_for_area(area):
    """A copied/translated area cannot accidentally reuse a stale marker."""
    marker = area.get('confirmed_wheel_geometry') or {}
    if (not isinstance(marker, dict)
            or _frame(marker.get('area_bounds')) != _area_bounds(area)
            or marker.get('target_id') != area.get('id')
            or marker.get('target_name') != area.get('name')):
        return None
    return _geometry(marker, area)


def mark_confirmed_geometry(area, geometry):
    measured = _geometry(geometry, area)
    if measured is not None:
        area['confirmed_wheel_geometry'] = {
            **measured, 'area_bounds': _area_bounds(area),
            'target_id': area.get('id'), 'target_name': area.get('name'),
        }


class WheelGeometryScan:
    def __init__(self, key, serial, entries, allow_measure=True):
        self.key = key
        self.serial = serial
        self.entries = {k: dict(v) for k, v in entries.items()}
        self.reused = 0
        self.measured = 0
        self.allow_measure = allow_measure

    def detect(self, area, detector):
        source_key = (str(area.get('id', '')), str(area.get('name', '')),
                      _area_bounds(area), _frame(area.get('label_frame')))
        if self.key is not None and source_key in self.entries:
            self.reused += 1
            return {**self.entries[source_key], 'confirmed_for_layout': True}
        result = detector(area)
        measured = _geometry(result, area)
        if self.key is not None and measured is not None and self.allow_measure:
            self.entries[source_key] = measured
            self.measured += 1
            return {**measured, 'confirmed_for_layout': True}
        return result


class WheelGeometryCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._serial = 0
        self._key = None
        self._entries = {}

    def begin_scan(self, key, *, allow_measure=True):
        with self._lock:
            self._serial += 1
            return WheelGeometryScan(
                key, self._serial, self._entries if key == self._key else {},
                allow_measure=allow_measure,
            )

    def commit(self, scan):
        with self._lock:
            if scan.serial != self._serial:
                return False
            self._key = scan.key
            self._entries = ({k: dict(v) for k, v in scan.entries.items()}
                             if scan.key is not None else {})
            return True
