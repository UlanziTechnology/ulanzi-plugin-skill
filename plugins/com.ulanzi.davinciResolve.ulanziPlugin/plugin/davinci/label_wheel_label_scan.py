"""Scan UI trees for DaVinci color-wheel labels."""

from .config import WHEEL_LABEL_NAMES, WHEEL_ORDER
from .label_window_matcher import canonical_wheel_name


def _label_center_y(label):
    _x, y, _w, h = label['frame']
    return y + h / 2


def _cluster_rows(labels):
    rows = []
    for label in sorted(labels, key=lambda item: (_label_center_y(item), item['frame'][0])):
        center_y = _label_center_y(label)
        tolerance = max(10, label['frame'][3] * 1.5)
        matched = None
        for row in rows:
            if abs(center_y - row['center_y']) <= max(tolerance, row['tolerance']):
                matched = row
                break
        if matched is None:
            rows.append({'center_y': center_y, 'tolerance': tolerance, 'items': [label]})
            continue
        matched['items'].append(label)
        matched['center_y'] = sum(_label_center_y(item) for item in matched['items']) / len(matched['items'])
        matched['tolerance'] = max(matched['tolerance'], tolerance)
    return rows


def _dedupe_row(row_items):
    by_name = {}
    for item in sorted(row_items, key=lambda label: label['frame'][0]):
        by_name.setdefault(item['name'], item)
    return [by_name[name] for name in WHEEL_ORDER if name in by_name]


def _choose_main_label_row(labels):
    if len(labels) <= len(WHEEL_ORDER):
        return sorted(labels, key=lambda item: item['frame'][0])

    best = None
    for row in _cluster_rows(labels):
        row_items = row['items']
        deduped = _dedupe_row(row_items)
        if len(deduped) < 2:
            continue
        left = min(item['frame'][0] for item in row_items)
        right = max(item['frame'][0] + item['frame'][2] for item in row_items)
        score = len({item['name'] for item in deduped}) * 1000 + len(row_items) * 10 + (right - left)
        candidate = {'score': score, 'items': deduped}
        if best is None or candidate['score'] > best['score']:
            best = candidate

    if best:
        return best['items']

    return _dedupe_row(labels)


def scan_wheel_labels(
    root,
    *,
    get_element_text_fn,
    get_element_frame_fn,
    get_element_children_fn,
    max_depth=80,
):
    results = []

    def traverse(element, depth=0):
        if element is None or depth > max_depth:
            return

        text = get_element_text_fn(element)
        if text in WHEEL_LABEL_NAMES:
            rect = get_element_frame_fn(element)
            if rect:
                results.append({'name': canonical_wheel_name(text), 'frame': rect})

        children = get_element_children_fn(element)
        if children:
            for child in children:
                traverse(child, depth + 1)

    traverse(root)
    return _choose_main_label_row(results)


__all__ = ['scan_wheel_labels']
