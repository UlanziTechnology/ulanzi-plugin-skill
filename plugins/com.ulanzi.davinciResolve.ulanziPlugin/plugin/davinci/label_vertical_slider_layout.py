"""Vertical-slider target layout inference for DaVinci UI labels."""

from .config import (
    ENABLE_VERTICAL_SLIDER_RECOGNITION,
    VERTICAL_SLIDER_CHANNELS,
    VERTICAL_SLIDER_MAX_HEIGHT,
    VERTICAL_SLIDER_MIN_HEIGHT,
    VERTICAL_SLIDER_OVERLAY_SIDE_PADDING,
    VERTICAL_SLIDER_OVERLAY_VERTICAL_PADDING,
    VERTICAL_SLIDER_SEARCH_BOTTOM_GAP,
    VERTICAL_SLIDER_SEARCH_SIDE_MARGIN,
    VERTICAL_SLIDER_SEARCH_TOP_GAP,
    VERTICAL_SLIDER_TARGET_WIDTH,
    WHEEL_ORDER,
)


def make_vertical_slider_target(name, channel_name, channel_index, track, inp=None):
    track_x = track['x']
    track_y = track['y']
    track_w = track['w']
    track_h = track['h']
    center_x = track_x + track_w / 2
    target_width = max(VERTICAL_SLIDER_TARGET_WIDTH, track_w + 12)
    target_x = center_x - target_width / 2
    target_y = track_y
    overlay_x = track_x - VERTICAL_SLIDER_OVERLAY_SIDE_PADDING
    overlay_w = track_w + VERTICAL_SLIDER_OVERLAY_SIDE_PADDING * 2
    overlay_y = track_y - VERTICAL_SLIDER_OVERLAY_VERTICAL_PADDING
    overlay_h = track_h + VERTICAL_SLIDER_OVERLAY_VERTICAL_PADDING * 2
    value = inp.get('value') if inp else None
    return {
        'id': f"vslider:{name}:{channel_index}:{round(center_x)}:{round(track_y)}",
        'name': f"{name} {channel_name}",
        'type': 'vertical_slider',
        'x': target_x,
        'y': target_y,
        'w': target_width,
        'h': track_h,
        'overlay_x': overlay_x,
        'overlay_y': overlay_y,
        'overlay_w': overlay_w,
        'overlay_h': overlay_h,
        'center_x': center_x,
        'center_y': track_y + track_h / 2,
        'source_frame': (track_x, track_y, track_w, track_h),
        'value': value,
        'priority': 20,
        'drag_axis': 'y',
    }


def infer_vertical_slider_areas_from_numeric_inputs(
    numeric_inputs,
    labels,
    *,
    is_windows,
    find_grouped_numeric_control_row_fn,
    find_grouped_numeric_control_rows_fn=None,
    detect_tracks_fn,
    debug_slow_fn=None,
):
    if not (ENABLE_VERTICAL_SLIDER_RECOGNITION and numeric_inputs):
        return []

    if find_grouped_numeric_control_rows_fn:
        candidates = find_grouped_numeric_control_rows_fn(numeric_inputs)
    else:
        best = find_grouped_numeric_control_row_fn(numeric_inputs)
        candidates = [best] if best else []

    if not candidates:
        if debug_slow_fn:
            debug_slow_fn(f"vertical sliders skipped no grouped numeric rows inputs={len(numeric_inputs)}")
        return []

    rejection_reasons = []
    for best in candidates[:6]:
        groups = best['groups'][:len(WHEEL_ORDER)]
        if len(groups) < 3:
            rejection_reasons.append(f"groups={len(groups)}")
            continue
        if sum(1 for group in groups if len(group) >= 3) < 2:
            rejection_reasons.append(
                "short-groups="
                + ','.join(str(len(group)) for group in groups)
            )
            continue

        label_by_nearest = []
        for group in groups:
            group_left = min(inp['frame'][0] for inp in group)
            group_right = max(inp['frame'][0] + inp['frame'][2] for inp in group)
            group_center = (group_left + group_right) / 2
            group_row_top = min(inp['frame'][1] for inp in group)
            nearest = None
            nearest_distance = None
            for label in labels:
                if label['frame'][1] + label['frame'][3] >= group_row_top:
                    continue
                label_x, _label_y, label_w, _label_h = label['frame']
                distance = abs((label_x + label_w / 2) - group_center)
                if nearest is None or distance < nearest_distance:
                    nearest = label
                    nearest_distance = distance
            label_by_nearest.append(nearest if nearest_distance is not None and nearest_distance <= 110 else None)

        areas = []
        row_top = min(inp['frame'][1] for inp in best['row']['items'])
        row_track_counts = []
        for group_index, group in enumerate(groups):
            label = label_by_nearest[group_index]
            name = label['name'] if label else WHEEL_ORDER[group_index]
            ordered_group = sorted(group, key=lambda item: item['frame'][0])
            group_left = min(inp['frame'][0] for inp in ordered_group)
            group_right = max(inp['frame'][0] + inp['frame'][2] for inp in ordered_group)
            group_row_top = min(inp['frame'][1] for inp in ordered_group)
            if label:
                _label_x, label_y, _label_w, label_h = label['frame']
                search_top = label_y + label_h + VERTICAL_SLIDER_SEARCH_TOP_GAP
            else:
                search_top = group_row_top - VERTICAL_SLIDER_MAX_HEIGHT
            search_bottom = group_row_top - VERTICAL_SLIDER_SEARCH_BOTTOM_GAP
            search_rect = (
                group_left - VERTICAL_SLIDER_SEARCH_SIDE_MARGIN,
                search_top,
                (group_right - group_left) + VERTICAL_SLIDER_SEARCH_SIDE_MARGIN * 2,
                search_bottom - search_top,
            )
            if search_rect[2] <= 0 or search_rect[3] < VERTICAL_SLIDER_MIN_HEIGHT:
                row_track_counts.append(0)
                continue

            tracks = detect_tracks_fn(search_rect)
            row_track_counts.append(len(tracks))
            if len(tracks) < min(3, len(ordered_group)):
                continue

            if len(tracks) > len(ordered_group):
                tracks = sorted(tracks, key=lambda track: track.get('score', 0), reverse=True)[:len(ordered_group)]
                tracks.sort(key=lambda track: track['x'])

            channel_names = (
                VERTICAL_SLIDER_CHANNELS[1:]
                if len(tracks) == 3
                else VERTICAL_SLIDER_CHANNELS
            )
            for channel_index, track in enumerate(tracks):
                inp = ordered_group[channel_index] if channel_index < len(ordered_group) else None
                channel_name = (
                    channel_names[channel_index]
                    if channel_index < len(channel_names)
                    else str(channel_index + 1)
                )
                target = make_vertical_slider_target(
                    name,
                    channel_name,
                    channel_index,
                    track,
                    inp,
                )
                if target:
                    areas.append(target)

        if areas:
            if debug_slow_fn:
                debug_slow_fn(
                    "vertical sliders inferred "
                    f"count={len(areas)} row_y={row_top:.0f} "
                    f"tracks={','.join(str(count) for count in row_track_counts)} "
                    f"names={','.join(area['name'] for area in areas[:8])}"
                )
            return areas

        rejection_reasons.append(
            f"row_y={row_top:.0f} tracks="
            + ','.join(str(count) for count in row_track_counts)
        )

    if debug_slow_fn:
        debug_slow_fn(
            "vertical sliders inferred count=0 "
            f"candidates={len(candidates)} reasons={' | '.join(rejection_reasons[:6])}"
        )
    return []


def infer_vertical_slider_areas_from_controls(sliders, labels, debug_slow_fn=None):
    """Build Color Bars targets from native AX/UIA vertical slider elements."""
    if not (ENABLE_VERTICAL_SLIDER_RECOGNITION and sliders):
        return []

    candidates = []
    for slider in sliders:
        x, y, w, h = slider.get('frame') or (0, 0, 0, 0)
        if h < VERTICAL_SLIDER_MIN_HEIGHT or h > VERTICAL_SLIDER_MAX_HEIGHT:
            continue
        if w <= 0 or w > max(48, VERTICAL_SLIDER_TARGET_WIDTH * 1.5) or h <= w * 2:
            continue
        candidates.append(slider)
    if len(candidates) < 3:
        return []

    clusters = []
    for slider in sorted(candidates, key=lambda item: (item['frame'][1], item['frame'][0])):
        _x, y, _w, h = slider['frame']
        cluster = next(
            (
                item for item in clusters
                if abs(item['y'] - y) <= 8 and abs(item['h'] - h) <= 12
            ),
            None,
        )
        if cluster is None:
            clusters.append({'y': y, 'h': h, 'items': [slider]})
        else:
            cluster['items'].append(slider)

    cluster = max(clusters, key=lambda item: len(item['items']))
    ordered = sorted(cluster['items'], key=lambda item: item['frame'][0])
    if len(ordered) < 3:
        return []

    label_groups = []
    ordered_labels = sorted(labels, key=lambda item: item['frame'][0])
    if ordered_labels:
        for label in ordered_labels[:len(WHEEL_ORDER)]:
            lx, _ly, lw, _lh = label['frame']
            label_center = lx + lw / 2
            group = [
                slider for slider in ordered
                if abs((slider['frame'][0] + slider['frame'][2] / 2) - label_center) <= 95
            ]
            if group:
                label_groups.append((label['name'], group))
    else:
        groups = []
        current = [ordered[0]]
        for previous, slider in zip(ordered, ordered[1:]):
            previous_center = previous['frame'][0] + previous['frame'][2] / 2
            center = slider['frame'][0] + slider['frame'][2] / 2
            if center - previous_center > 60:
                groups.append(current)
                current = [slider]
            else:
                current.append(slider)
        groups.append(current)
        label_groups = list(zip(WHEEL_ORDER, groups[:len(WHEEL_ORDER)]))

    areas = []
    seen_centers = set()
    for name, group in label_groups:
        group = sorted(group, key=lambda item: item['frame'][0])
        channel_names = VERTICAL_SLIDER_CHANNELS[1:] if len(group) == 3 else VERTICAL_SLIDER_CHANNELS
        for channel_index, slider in enumerate(group[:len(channel_names)]):
            x, y, w, h = slider['frame']
            center_key = (round(x + w / 2), round(y))
            if center_key in seen_centers:
                continue
            seen_centers.add(center_key)
            track = {'x': x, 'y': y, 'w': w, 'h': h}
            target = make_vertical_slider_target(
                name,
                channel_names[channel_index],
                channel_index,
                track,
                slider,
            )
            target['source'] = 'accessibility-slider'
            areas.append(target)

    if debug_slow_fn and areas:
        debug_slow_fn(
            "vertical sliders inferred from accessibility "
            f"count={len(areas)} names={','.join(area['name'] for area in areas[:8])}"
        )
    return areas


__all__ = [
    'infer_vertical_slider_areas_from_controls',
    'infer_vertical_slider_areas_from_numeric_inputs',
    'make_vertical_slider_target',
]
