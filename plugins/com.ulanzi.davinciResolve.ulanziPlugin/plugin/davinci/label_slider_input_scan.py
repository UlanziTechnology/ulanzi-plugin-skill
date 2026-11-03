"""Scan accessibility trees for native vertical slider controls."""


def scan_vertical_slider_inputs(
    root,
    *,
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

        role = str(get_element_role_fn(element) or '')
        if 'Slider' in role:
            rect = get_element_frame_fn(element)
            if rect:
                x, y, w, h = rect
                if w > 0 and h > w * 2:
                    frame_key = tuple(round(float(value)) for value in rect)
                    if frame_key not in seen_frames:
                        seen_frames.add(frame_key)
                        results.append({
                            'value': str(get_element_text_fn(element) or '').strip(),
                            'frame': (float(x), float(y), float(w), float(h)),
                        })

        for child in get_element_children_fn(element) or []:
            traverse(child, depth + 1)

    traverse(root)
    return results


__all__ = ['scan_vertical_slider_inputs']
