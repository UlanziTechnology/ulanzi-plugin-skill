"""Color page activation helper for DaVinci UI discovery."""


def activate_color_page(
    finder,
    *,
    target_texts,
    is_windows,
    simulate_mouse_drag_fn,
    sleep_fn,
    ax_perform_action_fn,
    press_action,
    get_attr_fn,
    parse_ax_frame_fn,
):
    color_element = finder.find_first_text(target_texts)
    if not color_element:
        return False, "Color tab not found"

    if is_windows:
        if finder._click_element(color_element):
            sleep_fn(0.8)
            finder.refresh_main_window()
            return True, "Clicked Color tab"

        rect = finder._get_element_frame(color_element)
        if not rect:
            return False, "Color tab found but no frame"
        x, y, width, height = rect
        center_x = x + width / 2
        center_y = y + height / 2
        simulate_mouse_drag_fn(center_x, center_y, center_x, center_y, duration=0.05)
        sleep_fn(0.8)
        finder.refresh_main_window()
        return True, "Clicked Color tab via simulated mouse"

    try:
        if ax_perform_action_fn and ax_perform_action_fn(color_element, press_action) == 0:
            sleep_fn(0.8)
            finder.refresh_main_window()
            return True, "Clicked Color tab"
    except Exception:
        pass

    frame = get_attr_fn(color_element, 'AXFrame')
    rect = parse_ax_frame_fn(frame)
    if not rect:
        return False, "Color tab found but no frame"

    x, y, width, height = rect
    center_x = x + width / 2
    center_y = y + height / 2
    simulate_mouse_drag_fn(center_x, center_y, center_x, center_y, duration=0.05)
    sleep_fn(0.8)
    finder.refresh_main_window()
    return True, "Clicked Color tab via simulated mouse"


__all__ = ['activate_color_page']
