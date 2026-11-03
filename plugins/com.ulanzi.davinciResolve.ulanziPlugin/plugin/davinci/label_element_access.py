"""Cross-platform UI element access helpers for DaVinci label discovery."""

import re


def get_ax_attribute(element, attr, *, is_mac, copy_attr_value_fn):
    if not is_mac or element is None or copy_attr_value_fn is None:
        return None
    err, val = copy_attr_value_fn(element, attr, None)
    return val if err == 0 else None


def parse_ax_frame_value(frame):
    if frame is None:
        return None
    str_repr = str(frame)
    match = re.search(r'x:([-\d.]+)\s+y:([-\d.]+)\s+w:([-\d.]+)\s+h:([-\d.]+)', str_repr)
    if match:
        return (
            float(match.group(1)),
            float(match.group(2)),
            float(match.group(3)),
            float(match.group(4)),
        )
    return None


def get_element_text(element, *, is_windows, ax_text_attributes, get_attr_fn):
    if is_windows:
        for getter in (
            lambda: element.window_text(),
            lambda: element.element_info.name,
            lambda: element.element_info.automation_id,
            lambda: element.element_info.rich_text,
        ):
            try:
                value = getter()
            except Exception:
                value = None
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return ''

    for attr in ax_text_attributes:
        value = get_attr_fn(element, attr)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ''


def get_element_frame(element, *, is_windows, get_attr_fn, parse_ax_frame_fn):
    if is_windows:
        try:
            rect = element.rectangle()
            return (
                float(rect.left),
                float(rect.top),
                float(rect.width()),
                float(rect.height()),
            )
        except Exception:
            return None

    frame = get_attr_fn(element, 'AXFrame')
    return parse_ax_frame_fn(frame)


def get_element_children(element, *, is_windows, get_attr_fn):
    if is_windows:
        try:
            return element.children()
        except Exception:
            return []
    return get_attr_fn(element, 'AXChildren') or []


def get_element_role(element, *, is_windows, get_attr_fn):
    if is_windows:
        try:
            return element.element_info.control_type
        except Exception:
            return ''
    return get_attr_fn(element, 'AXRole')


def click_element(element, *, is_windows, ax_perform_action_fn, press_action):
    if is_windows:
        for action in (
            lambda: element.invoke(),
            lambda: element.click_input(),
        ):
            try:
                action()
                return True
            except Exception:
                continue
        return False

    try:
        return ax_perform_action_fn(element, press_action) == 0
    except Exception:
        return False


__all__ = [
    'click_element',
    'get_ax_attribute',
    'get_element_children',
    'get_element_frame',
    'get_element_role',
    'get_element_text',
    'parse_ax_frame_value',
]
