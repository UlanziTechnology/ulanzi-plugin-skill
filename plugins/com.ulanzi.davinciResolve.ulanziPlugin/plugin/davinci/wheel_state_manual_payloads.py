"""Payload builders for manual wheel drag state."""


def wheel_manual_drag_payload(area, key, *, immediate=False, started_at=None):
    payload = {
        'area': area,
        'key': key,
        'name': area.get('name') if area else None,
    }
    if started_at is not None:
        payload['started_at'] = started_at
    if immediate:
        payload['immediate'] = True
    return payload


__all__ = ['wheel_manual_drag_payload']
