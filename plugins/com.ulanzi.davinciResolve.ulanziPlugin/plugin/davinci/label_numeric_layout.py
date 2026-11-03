"""Numeric-input row layout inference for DaVinci color controls."""

from .config import (
    WHEEL_ORDER,
    WHEEL_OVERLAY_HORIZONTAL_MARGIN,
    WHEEL_OVERLAY_VERTICAL_MARGIN,
)


def median(values, default=None):
    if not values:
        return default
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def group_numeric_rows(numeric_inputs, y_tolerance=8):
    rows = []
    for inp in sorted(numeric_inputs, key=lambda item: (item['frame'][1], item['frame'][0])):
        _x, y, _w, h = inp['frame']
        center_y = y + h / 2
        matched = None
        for row in rows:
            if abs(center_y - row['center_y']) <= y_tolerance:
                matched = row
                break
        if matched is None:
            rows.append({'center_y': center_y, 'items': [inp]})
        else:
            matched['items'].append(inp)
            matched['center_y'] = sum(
                item['frame'][1] + item['frame'][3] / 2 for item in matched['items']
            ) / len(matched['items'])
    for row in rows:
        row['items'].sort(key=lambda item: item['frame'][0])
    return rows


def split_numeric_row_into_groups(row_inputs):
    if not row_inputs:
        return []

    centers = [
        inp['frame'][0] + inp['frame'][2] / 2
        for inp in row_inputs
    ]
    gaps = [
        centers[index + 1] - centers[index]
        for index in range(len(centers) - 1)
    ]
    close_gaps = [gap for gap in gaps if gap <= 60]
    gap_threshold = 62
    if close_gaps:
        gap_threshold = max(55, min(90, median(close_gaps, 35) * 1.8))

    groups = []
    current = [row_inputs[0]]
    for index, gap in enumerate(gaps):
        if gap > gap_threshold:
            groups.append(current)
            current = [row_inputs[index + 1]]
        else:
            current.append(row_inputs[index + 1])
    groups.append(current)
    return [group for group in groups if len(group) >= 2]


def find_grouped_numeric_control_rows(numeric_inputs, min_groups=3):
    candidates = []
    for row in group_numeric_rows(numeric_inputs):
        groups = split_numeric_row_into_groups(row['items'])
        if len(groups) < min_groups:
            continue
        score = len(groups) * 100 + len(row['items'])
        candidates.append({'score': score, 'row': row, 'groups': groups})
    candidates.sort(key=lambda item: item['score'], reverse=True)
    return candidates


def find_grouped_numeric_control_row(numeric_inputs, min_groups=3):
    candidates = find_grouped_numeric_control_rows(numeric_inputs, min_groups)
    return candidates[0] if candidates else None


def infer_wheel_areas_from_numeric_inputs(
    numeric_inputs,
    labels,
    *,
    is_windows,
    debug_slow_fn=None,
):
    if not numeric_inputs:
        return []

    best = find_grouped_numeric_control_row(numeric_inputs)
    if not best:
        return []

    groups = best['groups'][:len(WHEEL_ORDER)]
    if len(groups) < 3:
        return []

    row_top = min(inp['frame'][1] for inp in best['row']['items'])
    row_bottom = max(inp['frame'][1] + inp['frame'][3] for inp in best['row']['items'])
    label_tops = [
        label['frame'][1] + label['frame'][3] + 5
        for label in labels
        if label['frame'][1] + label['frame'][3] < row_top
    ]
    area_top = median(label_tops, None)
    if area_top is None:
        group_widths = [
            max(inp['frame'][0] + inp['frame'][2] for inp in group) - min(inp['frame'][0] for inp in group)
            for group in groups
        ]
        inferred_size = max(120, min(220, median(group_widths, 150) + 20))
        area_top = row_top - inferred_size - 5

    area_bottom = row_top - 5
    area_height = area_bottom - area_top
    if area_height < 80:
        group_widths = [
            max(inp['frame'][0] + inp['frame'][2] for inp in group) - min(inp['frame'][0] for inp in group)
            for group in groups
        ]
        area_height = max(120, min(220, median(group_widths, 150) + 20))
        area_top = area_bottom - area_height

    label_by_nearest = []
    for group in groups:
        group_left = min(inp['frame'][0] for inp in group)
        group_right = max(inp['frame'][0] + inp['frame'][2] for inp in group)
        group_center = (group_left + group_right) / 2
        nearest = None
        nearest_distance = None
        for label in labels:
            label_x, _label_y, label_w, _label_h = label['frame']
            distance = abs((label_x + label_w / 2) - group_center)
            if nearest is None or distance < nearest_distance:
                nearest = label
                nearest_distance = distance
        label_by_nearest.append(nearest if nearest_distance is not None and nearest_distance <= 90 else None)

    areas = []
    for index, group in enumerate(groups):
        group_left = min(inp['frame'][0] for inp in group)
        group_right = max(inp['frame'][0] + inp['frame'][2] for inp in group)
        group_center = (group_left + group_right) / 2
        group_width = group_right - group_left
        area_width = max(area_height, group_width + 8)
        area_x = group_center - area_width / 2
        area_y = area_top
        name = label_by_nearest[index]['name'] if label_by_nearest[index] else WHEEL_ORDER[index]

        areas.append({
            'id': f"wheel:{name}",
            'name': name,
            'type': 'wheel',
            'x': area_x,
            'y': area_y,
            'w': area_width,
            'h': area_height,
            'overlay_x': area_x - WHEEL_OVERLAY_HORIZONTAL_MARGIN,
            'overlay_y': area_y - WHEEL_OVERLAY_VERTICAL_MARGIN,
            'overlay_w': area_width + WHEEL_OVERLAY_HORIZONTAL_MARGIN * 2,
            'overlay_h': area_height + WHEEL_OVERLAY_VERTICAL_MARGIN * 2,
            'center_x': area_x + area_width / 2,
            'center_y': area_y + area_height / 2,
            'label_frame': label_by_nearest[index]['frame'] if label_by_nearest[index] else None,
            'source': 'numeric-row',
            'priority': 0,
        })

    if debug_slow_fn:
        debug_slow_fn(
            "numeric row inferred wheels "
            f"count={len(areas)} row_y={row_top:.0f}-{row_bottom:.0f} "
            f"names={','.join(area['name'] for area in areas)}"
        )
    return areas
