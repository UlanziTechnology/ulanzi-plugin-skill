"""Scan UI trees for DaVinci numeric input values."""

import re


_NUMERIC_VALUE_RE = re.compile(r'^-?\d+\.\d+$')


def scan_numeric_inputs(
    root,
    *,
    is_windows,
    get_element_role_fn,
    get_element_text_fn,
    get_element_frame_fn,
    get_element_children_fn,
    max_depth=80,
):
    results = []
    seen_frames = set()

    def traverse(element, depth=0):
        if element is None or depth > max_depth:
            return

        role = get_element_role_fn(element)
        value = get_element_text_fn(element)
        rect = get_element_frame_fn(element)

        if rect and value and (is_windows or 'StaticText' in str(role)):
            val_str = str(value).strip()
            if _NUMERIC_VALUE_RE.match(val_str):
                frame_key = tuple(round(float(v)) for v in rect)
                if frame_key not in seen_frames:
                    seen_frames.add(frame_key)
                    results.append({'value': val_str, 'frame': rect})

        children = get_element_children_fn(element)
        if children:
            for child in children:
                traverse(child, depth + 1)

    traverse(root)
    return results


__all__ = ['scan_numeric_inputs']
