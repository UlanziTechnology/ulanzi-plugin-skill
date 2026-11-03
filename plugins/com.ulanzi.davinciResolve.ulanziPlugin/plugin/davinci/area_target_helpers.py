"""Small helpers for DaVinci target area identity and hit testing."""


def area_key(area):
    if not area:
        return None
    return area.get('id') or area.get('name')


def area_label(area):
    if not area:
        return 'Unknown'
    return area.get('name') or area.get('id') or 'Unknown'


def area_contains_point(area, mouse_x, mouse_y):
    return (
        area
        and area['x'] <= mouse_x <= area['x'] + area['w']
        and area['y'] <= mouse_y <= area['y'] + area['h']
    )


def area_at_point(areas, mouse_x, mouse_y):
    for area in sorted(areas, key=lambda item: item.get('priority', 0), reverse=True):
        if area_contains_point(area, mouse_x, mouse_y):
            return area
    return None


def wheel_area_at_point(areas, mouse_x, mouse_y):
    for area in sorted(areas, key=lambda item: item.get('priority', 0), reverse=True):
        if area.get('type') != 'wheel':
            continue
        if area_contains_point(area, mouse_x, mouse_y):
            return area
    return None


__all__ = [
    'area_at_point',
    'area_contains_point',
    'area_key',
    'area_label',
    'wheel_area_at_point',
]
