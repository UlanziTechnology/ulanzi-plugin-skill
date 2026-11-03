"""Invalidate one untrusted predicted wheel without touching native input/UI."""

from .area_target_helpers import area_key


def invalidate_predicted_wheel_visual(manager, area, _reason=None):
    if not area or area.get('type') != 'wheel' or not area.get('name'):
        return False
    key = area_key(area)
    store = getattr(manager, '_wheel_state_store', None)
    stored = store.get(key, area) if store is not None else None
    old_stored_handle = (stored or {}).get('last_detected_handle')
    name = area['name']
    previous = manager.handles.get(name)
    # A user reset/manual placement published after the old prediction is a
    # new authority. Retirement of that prediction must not erase it.
    source = str((previous or {}).get('source') or '')
    if source and not source.startswith('smooth_'):
        return False
    tombstone = {
        'source': 'smooth_visual_invalidated',
        'visual_invalidated': True,
        'updated_at': 0.0,
    }
    if previous is None:
        # A concurrent fresh detection/reset must win over this old retirement.
        previous = manager.handles.setdefault(name, tombstone)
        if previous is not tombstone:
            return False
    else:
        # Update only the dictionary we inspected. Fresh detection/reset
        # publishes a new dictionary; never overwrite that newer reference.
        previous.update(tombstone)
        for field in list(previous):
            if field not in tombstone:
                previous.pop(field, None)
        if manager.handles.get(name) is not previous:
            return False
    for attribute in ('_wheel_anchor_state', '_wheel_diameter_state'):
        state = getattr(manager, attribute, None)
        state_source = str((state or {}).get('source') or '')
        if (state and state.get('target_key') == key
                and (not state_source or state_source.startswith('smooth_'))):
            state.update(visual_invalidated=True, updated_at=0.0)
    if store is not None:
        store.invalidate_handle(key, expected_handle=old_stored_handle)
    return True


def refresh_invalidated_wheel_visual(manager, area):
    # The queued refresh may arrive after a fresh commit/reset. Read current
    # data, and never reapply a stale hidden flag to the replacement point.
    handle = manager.handles.get(area.get('name')) or {}
    if not handle:
        return
    refresh = getattr(manager, '_refresh_wheel_overlay_state_fn', None)
    if callable(refresh):
        refresh(area, area.get('name'))
