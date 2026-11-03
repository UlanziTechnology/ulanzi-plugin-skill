"""Assemble DaVinci hover target areas from label and numeric-input layouts."""

from .config import (
    WHEEL_OVERLAY_HORIZONTAL_MARGIN,
    WHEEL_OVERLAY_VERTICAL_MARGIN,
)
from .label_area_layout import (
    infer_label_wheel_areas,
    is_wheel_value_numeric,
    target_from_rect,
)
from .label_numeric_layout import (
    find_grouped_numeric_control_row,
    find_grouped_numeric_control_rows,
    infer_wheel_areas_from_numeric_inputs,
)
from .label_slider_layout import (
    make_slider_target,
    make_slider_target_from_numeric_group,
)
from .label_vertical_slider_layout import (
    infer_vertical_slider_areas_from_controls,
    infer_vertical_slider_areas_from_numeric_inputs,
)
from .layout_scan_guard import LayoutScanSuperseded
from .wheel_confirmed_geometry import mark_confirmed_geometry


WHEEL_GEOMETRY_SEARCH_MIN_SIZE = 140
WHEEL_GEOMETRY_TARGET_PADDING = 4
WHEEL_GEOMETRY_MIN_RADIUS = 18


def choose_wheel_areas(label_wheel_areas, inferred_wheel_areas):
    if inferred_wheel_areas and len(inferred_wheel_areas) >= max(2, len(label_wheel_areas)):
        return inferred_wheel_areas
    return label_wheel_areas


def _float_or_default(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _geometry_search_area(area):
    area_x = _float_or_default(area.get('x'), 0.0)
    area_y = _float_or_default(area.get('y'), 0.0)
    area_w = max(1.0, _float_or_default(area.get('w'), 1.0))
    area_h = max(1.0, _float_or_default(area.get('h'), 1.0))
    center_x = _float_or_default(area.get('center_x'), area_x + area_w / 2)
    center_y = _float_or_default(area.get('center_y'), area_y + area_h / 2)
    size = max(area_w, area_h, WHEEL_GEOMETRY_SEARCH_MIN_SIZE)

    if area_h < WHEEL_GEOMETRY_SEARCH_MIN_SIZE * 0.75:
        center_y += min((WHEEL_GEOMETRY_SEARCH_MIN_SIZE - area_h) * 0.25, 32)

    search_x = center_x - size / 2
    search_y = center_y - size / 2
    search_area = dict(area)
    search_area.update({
        'x': search_x,
        'y': search_y,
        'w': size,
        'h': size,
        'overlay_x': search_x - WHEEL_OVERLAY_HORIZONTAL_MARGIN,
        'overlay_y': search_y - WHEEL_OVERLAY_VERTICAL_MARGIN,
        'overlay_w': size + WHEEL_OVERLAY_HORIZONTAL_MARGIN * 2,
        'overlay_h': size + WHEEL_OVERLAY_VERTICAL_MARGIN * 2,
        'center_x': center_x,
        'center_y': center_y,
    })
    return search_area


def _source_with_suffix(area, suffix):
    source = area.get('source')
    if not source:
        return suffix
    if suffix in source.split('+'):
        return source
    return f"{source}+{suffix}"


def _area_from_wheel_geometry(area, geometry):
    center_x = _float_or_default(geometry.get('wheel_center_x'), None)
    center_y = _float_or_default(geometry.get('wheel_center_y'), None)
    radius = _float_or_default(geometry.get('wheel_radius'), None)
    if center_x is None or center_y is None or radius is None:
        return None
    if radius < WHEEL_GEOMETRY_MIN_RADIUS:
        return None

    target_radius = radius + WHEEL_GEOMETRY_TARGET_PADDING
    area_x = center_x - target_radius
    area_y = center_y - target_radius
    area_size = target_radius * 2
    refined = dict(area)
    refined.update({
        'x': area_x,
        'y': area_y,
        'w': area_size,
        'h': area_size,
        'overlay_x': area_x - WHEEL_OVERLAY_HORIZONTAL_MARGIN,
        'overlay_y': area_y - WHEEL_OVERLAY_VERTICAL_MARGIN,
        'overlay_w': area_size + WHEEL_OVERLAY_HORIZONTAL_MARGIN * 2,
        'overlay_h': area_size + WHEEL_OVERLAY_VERTICAL_MARGIN * 2,
        'center_x': center_x,
        'center_y': center_y,
        'source': _source_with_suffix(area, 'pixel-geometry'),
        'wheel_radius': radius,
        'visual_center_x': geometry.get('visual_center_x', center_x),
        'visual_center_y': geometry.get('visual_center_y', center_y),
        'visual_radius': radius,
    })
    if geometry.get('confirmed_for_layout'):
        mark_confirmed_geometry(refined, geometry)
    return refined


def refine_wheel_areas_with_geometry(wheel_areas, detect_wheel_circle_fn=None, debug_slow_fn=None):
    if not wheel_areas or not detect_wheel_circle_fn:
        return wheel_areas

    refined_areas = []
    for area in wheel_areas:
        try:
            geometry = detect_wheel_circle_fn(_geometry_search_area(area))
            refined = _area_from_wheel_geometry(area, geometry or {})
        except LayoutScanSuperseded:
            # Cancellation is not failed recognition: discard this scan rather
            # than falling back to partial/stale areas and scanning more wheels.
            raise
        except Exception as exc:
            if debug_slow_fn:
                debug_slow_fn(f"wheel geometry refine failed name={area.get('name')} error={exc}")
            refined = None

        if refined:
            refined_areas.append(refined)
            if debug_slow_fn:
                debug_slow_fn(
                    "wheel geometry refined "
                    f"name={refined.get('name')} "
                    f"center=({refined['center_x']:.0f},{refined['center_y']:.0f}) "
                    f"radius={refined['wheel_radius']:.0f}"
                )
        else:
            refined_areas.append(area)
    return refined_areas


def make_numeric_target(index, numeric_input, wheel_areas):
    rect = numeric_input['frame']
    value = numeric_input['value']
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return None

    target = target_from_rect(
        f"numeric:{index}:{round(x)}:{round(y)}",
        'numeric',
        f"Value {value}",
        rect,
    )
    target['drag_mode'] = (
        'underline'
        if is_wheel_value_numeric(rect, wheel_areas)
        else 'center'
    )
    return target


def _row_group_bounds(row_inputs):
    left = min(inp['frame'][0] for inp in row_inputs)
    right = max(inp['frame'][0] + inp['frame'][2] for inp in row_inputs)
    top = min(inp['frame'][1] for inp in row_inputs)
    bottom = max(inp['frame'][1] + inp['frame'][3] for inp in row_inputs)
    return left, top, right, bottom


def _vertical_slider_base_name(area):
    name = area.get('name') or 'Bars'
    parts = name.rsplit(' ', 1)
    return parts[0] if len(parts) == 2 else name


def make_bar_slider_targets(vertical_slider_areas, numeric_inputs, detect_track_fn=None):
    if not vertical_slider_areas or not numeric_inputs:
        return []

    targets = []
    seen = set()
    candidates = find_grouped_numeric_control_rows(numeric_inputs, min_groups=1)
    for candidate in candidates[:6]:
        for group in candidate.get('groups', []):
            if len(group) < 2:
                continue
            group_left, group_top, group_right, group_bottom = _row_group_bounds(group)
            matching_sliders = []
            for area in vertical_slider_areas:
                source_frame = area.get('source_frame')
                if source_frame:
                    track_x, track_y, track_w, track_h = source_frame
                    slider_center_x = track_x + track_w / 2
                    slider_bottom = track_y + track_h
                else:
                    slider_center_x = area.get('center_x', area.get('x', 0))
                    slider_bottom = area.get('y', 0) + area.get('h', 0)
                if not (group_left - 24 <= slider_center_x <= group_right + 24):
                    continue
                if slider_bottom > group_top + 8:
                    continue
                if group_top - slider_bottom > 140:
                    continue
                matching_sliders.append(area)

            if len(matching_sliders) < 2:
                continue

            target_key = (round(group_left), round(group_bottom))
            if target_key in seen:
                continue
            seen.add(target_key)

            name = _vertical_slider_base_name(matching_sliders[0])
            target = make_slider_target_from_numeric_group(
                name,
                group,
                detect_track_fn=detect_track_fn,
                target_id=f"slider:bar:{round(group_left)}:{round(group_bottom)}",
                priority=10,
            )
            if target:
                targets.append(target)

    return targets


def assemble_wheel_target_areas(
    labels,
    numeric_inputs,
    *,
    infer_wheel_areas_fn,
    infer_vertical_slider_areas_fn,
    detect_horizontal_slider_track_fn=None,
    detect_wheel_circle_fn=None,
    debug_slow_fn=None,
):
    vertical_slider_areas = infer_vertical_slider_areas_fn(numeric_inputs)
    if vertical_slider_areas:
        wheel_areas = []
    else:
        label_wheel_areas = infer_label_wheel_areas(labels, numeric_inputs)
        inferred_wheel_areas = infer_wheel_areas_fn(numeric_inputs)
        wheel_areas = choose_wheel_areas(label_wheel_areas, inferred_wheel_areas)
        wheel_areas = refine_wheel_areas_with_geometry(
            wheel_areas,
            detect_wheel_circle_fn=detect_wheel_circle_fn,
            debug_slow_fn=debug_slow_fn,
        )

    areas = list(wheel_areas)
    areas.extend(vertical_slider_areas)

    for index, numeric_input in enumerate(numeric_inputs):
        target = make_numeric_target(index, numeric_input, wheel_areas)
        if target:
            areas.append(target)

    if vertical_slider_areas:
        areas.extend(
            make_bar_slider_targets(
                vertical_slider_areas,
                numeric_inputs,
                detect_track_fn=detect_horizontal_slider_track_fn,
            )
        )
    else:
        for wheel_area in wheel_areas:
            slider_target = make_slider_target(
                wheel_area,
                numeric_inputs,
                detect_track_fn=detect_horizontal_slider_track_fn,
            )
            if slider_target:
                areas.append(slider_target)

    return areas


def calculate_wheel_target_areas(
    labels,
    numeric_inputs,
    *,
    is_windows,
    detect_vertical_slider_tracks_fn,
    vertical_sliders=None,
    detect_horizontal_slider_track_fn=None,
    detect_wheel_circle_fn=None,
    debug_slow_fn=None,
):
    return assemble_wheel_target_areas(
        labels,
        numeric_inputs,
        infer_wheel_areas_fn=lambda inputs: infer_wheel_areas_from_numeric_inputs(
            inputs,
            labels,
            is_windows=is_windows,
            debug_slow_fn=debug_slow_fn,
        ),
        infer_vertical_slider_areas_fn=(
            lambda inputs: (
                infer_vertical_slider_areas_from_controls(
                    vertical_sliders or [],
                    labels,
                    debug_slow_fn=debug_slow_fn,
                )
                or infer_vertical_slider_areas_from_numeric_inputs(
                    inputs,
                    labels,
                    is_windows=is_windows,
                    find_grouped_numeric_control_row_fn=find_grouped_numeric_control_row,
                    find_grouped_numeric_control_rows_fn=find_grouped_numeric_control_rows,
                    detect_tracks_fn=detect_vertical_slider_tracks_fn,
                    debug_slow_fn=debug_slow_fn,
                )
            )
        ),
        detect_horizontal_slider_track_fn=detect_horizontal_slider_track_fn,
        detect_wheel_circle_fn=detect_wheel_circle_fn,
        debug_slow_fn=debug_slow_fn,
    )


__all__ = [
    'assemble_wheel_target_areas',
    'calculate_wheel_target_areas',
    'choose_wheel_areas',
    'make_bar_slider_targets',
    'make_numeric_target',
    'refine_wheel_areas_with_geometry',
]
